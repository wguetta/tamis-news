from __future__ import annotations

import logging
import time
from typing import Optional

from news_clustering.clustering import cluster_articles
from news_clustering.config import NewsClusteringConfig
from news_clustering.llm import LlmClient
from news_clustering.prompts import load_prompts, render
from news_clustering.s3 import (
    article_cluster_rows,
    hashed_cluster_id,
    load_articles,
    load_manifest,
    load_ranked_checkpoint,
    make_s3_client,
    noise_article_rows,
    save_article_cluster_batch,
    save_cluster_batch,
    save_manifest,
    save_noise_article_cluster_ids,
    save_ranked_checkpoint,
    utc_now,
)
from news_clustering.scoring import rank_clusters, score_clusters

logger = logging.getLogger(__name__)


def summary_batches(clusters: list[dict], batch_size: int):
    for start in range(0, len(clusters), batch_size):
        yield start // batch_size, clusters[start : start + batch_size]


def _article_id(article: dict):
    value = article.get("id", article.get("article_id"))
    if value is None:
        return None
    return str(value)


def _preview_from_article(article: dict) -> dict:
    return {
        "id": _article_id(article),
        "title": article.get("title"),
        "source": article.get("source"),
        "topics": article.get("topics") or [],
    }


def _titles_from_previews(previews: list[dict]) -> str:
    return "\n\n".join(
        f"- {article['title']}"
        for article in previews
        if article.get("title")
    )


def attach_member_previews(clusters: list[dict], articles: list[dict]) -> None:
    by_id = {}
    by_cluster: dict[int, list[dict]] = {}
    for article in articles:
        article_id = _article_id(article)
        if article_id is not None:
            by_id[article_id] = article
        cluster_id = article.get("cluster_id")
        if cluster_id is None or cluster_id < 0:
            continue
        by_cluster.setdefault(cluster_id, []).append(article)
    for cluster in clusters:
        stored_ids = [str(article_id) for article_id in cluster.get("article_ids") or []]
        if stored_ids:
            members = [by_id[article_id] for article_id in stored_ids if article_id in by_id]
        else:
            members = by_cluster.get(cluster["cluster_id"], [])
            cluster["article_ids"] = [
                article_id
                for article_id in (_article_id(article) for article in members)
                if article_id is not None
            ]
        for article in members:
            article["cluster_id"] = cluster["cluster_id"]
        if members:
            cluster["articles"] = [_preview_from_article(article) for article in members]
            cluster["titles"] = _titles_from_previews(cluster["articles"])
        elif not cluster.get("titles") and not cluster.get("articles"):
            cluster["articles"] = []
            cluster["titles"] = ""


def _cluster_titles(cluster: dict) -> str:
    if cluster.get("titles"):
        return cluster["titles"]
    return _titles_from_previews(cluster.get("articles") or [])


def _summarize_cluster(
    llm: LlmClient, cluster: dict, prompts: dict, config: NewsClusteringConfig, job_date: str
) -> None:
    cluster["summary"] = llm.complete(
        instructions=prompts["system"],
        user=render(prompts["user"], {"titles": _cluster_titles(cluster)}),
        model=config.summarize_model,
    ).strip()
    cluster["hashed_cluster_id"] = hashed_cluster_id(
        job_date, cluster["cluster_id"], cluster["summary"]
    )


def cheap_summarize(
    llm: LlmClient, clusters: list[dict], config: NewsClusteringConfig, job_date: str
) -> dict:
    prompts = load_prompts("summarize")
    pending = list(clusters)
    errors = []
    for attempt in range(config.llm_max_retries + 1):
        still_pending = []
        for cluster in pending:
            try:
                _summarize_cluster(llm, cluster, prompts, config, job_date)
            except Exception as exc:
                still_pending.append(cluster)
                logger.warning(
                    "Summary failed for cluster %s (attempt %s/%s): %s",
                    cluster.get("cluster_id"),
                    attempt + 1,
                    config.llm_max_retries + 1,
                    exc,
                )
        pending = still_pending
        if not pending:
            break
        if attempt < config.llm_max_retries:
            time.sleep(1.5 * (2**attempt))

    for cluster in pending:
        cluster["summary"] = ""
        errors.append(f"cluster {cluster.get('cluster_id')}: summary failed after retries")
        logger.error("Giving up on summary for cluster %s", cluster.get("cluster_id"))
    return {
        "summarized": len(clusters) - len(pending),
        "failed": len(pending),
        "errors": errors,
    }


def _new_manifest(job_date: str, config: NewsClusteringConfig, reliability_count: int) -> dict:
    return {
        "date": job_date,
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "input": {},
        "reliability_sources": reliability_count,
        "batch_size": config.summary_batch_size,
        "cluster_count": 0,
        "ranked_checkpoint": None,
        "noise_article_ids": [],
        "noise_key": None,
        "batches": [],
        "errors": [],
    }


def _completed_batch_indexes(manifest: dict) -> set[int]:
    return {batch["index"] for batch in manifest.get("batches", [])}


def prepare_clusters(config: Optional[NewsClusteringConfig] = None, llm: Optional[LlmClient] = None):
    """Load today's news, cluster, score, rank, summarize in batches of 25, and persist."""
    config = config or NewsClusteringConfig.from_env()
    llm = llm or LlmClient(config)
    job_date = config.resolve_job_date()
    logger.info("Starting clustering job for date=%s", job_date)

    reliabilities = config.load_reliabilities()
    s3 = make_s3_client(config)
    manifest = load_manifest(s3, config.output_s3_bucket, job_date) or _new_manifest(
        job_date, config, len(reliabilities)
    )
    manifest["status"] = "running"
    manifest["reliability_sources"] = len(reliabilities)
    save_manifest(s3, config.output_s3_bucket, manifest)

    articles = []
    try:
        ranked_clusters = load_ranked_checkpoint(s3, config.output_s3_bucket, job_date)
        if ranked_clusters is not None:
            logger.info(
                "Resuming from ranked checkpoint (%s clusters)",
                len(ranked_clusters),
            )
            articles, input_meta = load_articles(config, s3)
            attach_member_previews(ranked_clusters, articles)
        else:
            articles, input_meta = load_articles(config, s3)
            manifest["input"] = {
                "bucket": config.s3_bucket,
                "date": input_meta["date"],
                "run": input_meta["run"],
                "keys": input_meta["keys"],
                "article_count": len(articles),
            }
            save_manifest(s3, config.output_s3_bucket, manifest)

            embeddings, labels = cluster_articles(articles, config)
            clusters = score_clusters(articles, embeddings, labels, config)
            ranked_clusters = rank_clusters(clusters, config)
            attach_member_previews(ranked_clusters, articles)
            manifest["noise_article_ids"] = [
                article["id"]
                for article in articles
                if article.get("cluster_id") == -1 and article.get("id") is not None
            ]
            checkpoint_key = save_ranked_checkpoint(
                s3, config.output_s3_bucket, job_date, ranked_clusters
            )
            manifest["ranked_checkpoint"] = checkpoint_key
            manifest["cluster_count"] = len(ranked_clusters)
            save_manifest(s3, config.output_s3_bucket, manifest)
            logger.info("Ranked %s clusters; checkpoint saved", len(ranked_clusters))

        manifest["cluster_count"] = len(ranked_clusters)
        done = _completed_batch_indexes(manifest)
        for batch_index, batch in summary_batches(ranked_clusters, config.summary_batch_size):
            if batch_index in done:
                logger.info("Skipping already written summary batch %s", batch_index)
                continue
            logger.info(
                "Summarizing batch %s (%s clusters)",
                batch_index,
                len(batch),
            )
            summary_stats = cheap_summarize(llm, batch, config, job_date)
            if summary_stats["failed"]:
                manifest["errors"].extend(summary_stats["errors"])
                logger.error(
                    "Batch %s not checkpointed (%s failed summaries); next run will retry it",
                    batch_index,
                    summary_stats["failed"],
                )
                save_manifest(s3, config.output_s3_bucket, manifest)
                continue
            key = save_cluster_batch(s3, config.output_s3_bucket, job_date, batch_index, batch)
            article_rows = article_cluster_rows(articles, batch)
            article_key = save_article_cluster_batch(
                s3, config.article_cluster_ids_s3_bucket, job_date, batch_index, article_rows
            )
            logger.info(
                "Wrote %s article-cluster ids for batch %s",
                len(article_rows),
                batch_index,
            )
            manifest["batches"].append(
                {
                    "index": batch_index,
                    "key": key,
                    "article_cluster_ids_key": article_key,
                    "cluster_ids": [cluster["cluster_id"] for cluster in batch],
                    "hashed_cluster_ids": [cluster["hashed_cluster_id"] for cluster in batch],
                    "cluster_count": len(batch),
                    "summarized": summary_stats["summarized"],
                    "failed_summaries": 0,
                    "written_at": utc_now(),
                }
            )
            save_manifest(s3, config.output_s3_bucket, manifest)

        expected_batches = (
            (len(ranked_clusters) + config.summary_batch_size - 1) // config.summary_batch_size
            if ranked_clusters
            else 0
        )
        if len(manifest["batches"]) < expected_batches:
            manifest["status"] = "failed"
        else:
            if not manifest.get("noise_key"):
                noise_rows = noise_article_rows(
                    articles, job_date, manifest.get("noise_article_ids")
                )
                manifest["noise_key"] = save_noise_article_cluster_ids(
                    s3, config.article_cluster_ids_s3_bucket, job_date, noise_rows
                )
                logger.info("Wrote %s noise article-cluster ids", len(noise_rows))
            manifest["status"] = "partial" if manifest["errors"] else "success"
        manifest["finished_at"] = utc_now()
        save_manifest(s3, config.output_s3_bucket, manifest)
        logger.info(
            "Job %s for date=%s: %s clusters in %s batches",
            manifest["status"],
            job_date,
            len(ranked_clusters),
            len(manifest["batches"]),
        )
        return {
            "s3_run": (manifest.get("input") or {}).get("run"),
            "articles": articles,
            "ranked_clusters": ranked_clusters,
            "manifest": manifest,
        }
    except Exception:
        manifest["status"] = "failed"
        manifest["finished_at"] = utc_now()
        try:
            save_manifest(s3, config.output_s3_bucket, manifest)
        except Exception:
            logger.exception("Could not write failed manifest")
        raise
