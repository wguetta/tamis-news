"""Core RSS article enrichment pipeline functions."""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import trafilatura
from botocore.exceptions import BotoCoreError, ClientError
from tqdm import tqdm

import config
from schemas import ENTITY_LABELS, TOPIC_LABELS

# Required for PyTorch / CUDA multiprocessing on Linux EC2.
mp.set_start_method("spawn", force=True)

logger = logging.getLogger(__name__)

# Loaded once per worker process by init_worker().
_extractor = None


from errors import EmbeddingError, EnrichmentError, PipelineError, S3LoadError, S3SaveError
from embeddings import enrich_and_embed_batch


def get_s3_client():
    """Create a boto3 S3 client using credentials from config."""
    return boto3.client(
        "s3",
        aws_access_key_id=config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
        region_name=config.AWS_REGION,
    )


def generate_hour_prefixes(
    n: int,
    reference: datetime | None = None,
) -> list[str]:
    """
    Build the last N hourly S3 partition prefixes from the clock.

    Avoids scanning the entire bucket, which does not scale in production.
    Example output: date=2026-07-06/hour=21/
    """
    if n <= 0:
        raise ValueError("n must be a positive integer")

    reference = (reference or datetime.now(timezone.utc)).astimezone(timezone.utc)
    prefixes: list[str] = []

    for hour_offset in range(n - 1, -1, -1):
        partition_time = reference - timedelta(hours=hour_offset)
        prefixes.append(
            f"date={partition_time:%Y-%m-%d}/hour={partition_time:%H}/"
        )

    return prefixes


def load_last_n_hours(
    s3_client,
    bucket: str,
    n: int,
) -> list[dict[str, Any]]:
    """Load all JSONL stories from the latest N hourly partitions."""
    paginator = s3_client.get_paginator("list_objects_v2")
    hour_prefixes = generate_hour_prefixes(n)
    stories: list[dict[str, Any]] = []

    logger.info("Loading articles from %d hourly partitions.", len(hour_prefixes))

    for prefix in hour_prefixes:
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    if not key.endswith(".jsonl"):
                        continue

                    logger.debug("Reading %s", key)

                    try:
                        response = s3_client.get_object(Bucket=bucket, Key=key)
                    except ClientError as exc:
                        logger.error("Failed to read s3://%s/%s: %s", bucket, key, exc)
                        continue

                    for line in response["Body"].iter_lines():
                        if not line:
                            continue
                        try:
                            stories.append(json.loads(line))
                        except json.JSONDecodeError as exc:
                            logger.warning(
                                "Skipping invalid JSON line in s3://%s/%s: %s",
                                bucket,
                                key,
                                exc,
                            )
        except (ClientError, BotoCoreError) as exc:
            raise S3LoadError(
                f"Failed to list or load objects under prefix '{prefix}' in bucket '{bucket}'"
            ) from exc

    logger.info("Loaded %d raw articles from S3.", len(stories))
    return stories


def remove_duplicates(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one article per title, preferring the longer description."""
    unique_articles: dict[str, dict[str, Any]] = {}

    for article in articles:
        title = article.get("title", "")
        description = article.get("description") or ""

        if title not in unique_articles:
            unique_articles[title] = article
            continue

        existing_article = unique_articles[title]
        existing_description = existing_article.get("description") or ""

        if len(description) > len(existing_description):
            unique_articles[title] = article

    deduped = list(unique_articles.values())
    logger.info(
        "Deduplicated %d articles down to %d unique titles.",
        len(articles),
        len(deduped),
    )
    return deduped


def enrich_articles_with_contents(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch and extract article body text from each article URL."""
    enriched_count = 0

    for article in tqdm(articles, desc="Fetching article content"):
        article["content"] = ""
        link = article.get("link")

        if not link:
            logger.warning("Article missing link, skipping content fetch: %s", article.get("title"))
            continue

        try:
            downloaded = trafilatura.fetch_url(link)

            if not downloaded:
                logger.warning("Failed to fetch %s", link)
                continue

            content = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                favor_precision=True,
            )

            if content and len(content.strip()) >= config.MIN_CONTENT_LENGTH:
                article["content"] = content.strip()
                enriched_count += 1
            else:
                logger.info("Little or no content extracted from %s", link)

        except Exception:
            logger.exception("Error fetching content for %s", link)

    logger.info(
        "Content enrichment complete: %d/%d articles have extracted content.",
        enriched_count,
        len(articles),
    )
    return articles


def build_full_content(article: dict[str, Any], word_count_limit: int) -> str:
    """Combine title, description, and content into a truncated full_content field."""
    title = article.get("title") or ""
    description = article.get("description") or ""
    content = article.get("content") or ""

    full_content = f"Title: {title}. Description: {description}"
    if content:
        full_content += f". Content: {content}"

    return " ".join(full_content.split()[:word_count_limit])


def add_full_content_to_articles(
    articles: list[dict[str, Any]],
    word_count_limit: int,
) -> list[dict[str, Any]]:
    """Attach a truncated full_content field to every article."""
    for article in articles:
        article["full_content"] = build_full_content(article, word_count_limit)
    return articles


def build_batch_s3_key(run_date: str, run_id: str, batch_number: int) -> str:
    """
    Build a unique S3 key for a processed batch.

    Example:
        date=2026-07-06/run=20260706T211530Z/batch=0001.jsonl
    """
    return (
        f"date={run_date}/"
        f"run={run_id}/"
        f"batch={batch_number:04d}.jsonl"
    )


def save_batch_to_s3(
    s3_client,
    articles: list[dict[str, Any]],
    bucket: str,
    run_date: str,
    run_id: str,
    batch_number: int,
) -> str:
    """Save a batch of processed articles as JSONL to S3."""
    if not articles:
        raise S3SaveError(f"Refusing to save empty batch {batch_number}")

    key = build_batch_s3_key(run_date, run_id, batch_number)

    try:
        body = "\n".join(
            json.dumps(story, ensure_ascii=False)
            for story in articles
        )

        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
    except (ClientError, BotoCoreError) as exc:
        raise S3SaveError(
            f"Failed to upload batch {batch_number} to s3://{bucket}/{key}"
        ) from exc

    logger.info(
        "Saved batch %04d (%d articles) to s3://%s/%s",
        batch_number,
        len(articles),
        bucket,
        key,
    )
    return key


def _configure_worker_logging(log_file_path: str) -> None:
    """Configure logging inside worker processes spawned by ProcessPoolExecutor."""
    root_logger = logging.getLogger()
    if any(
        isinstance(handler, logging.FileHandler)
        and getattr(handler, "baseFilename", None) == str(log_file_path)
        for handler in root_logger.handlers
    ):
        return

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(processName)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def init_worker(log_file_path: str, model_name: str) -> None:
    """Initialize one worker process: logging, torch threading, and GLiNER model."""
    global _extractor

    _configure_worker_logging(log_file_path)

    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)

    from gliner2 import GLiNER2

    logger.info("Loading GLiNER model '%s' in worker.", model_name)
    _extractor = GLiNER2.from_pretrained(model_name)
    logger.info("Worker initialization complete.")


def process_article(article: dict[str, Any]) -> dict[str, Any]:
    """
    Extract topics and entities for a single article.

    Failures are captured on the article itself so the batch can still be saved.
    """
    global _extractor

    article["topics"] = []
    article["entities"] = []
    article["extraction_error"] = None

    try:
        full_content = article.get("full_content", "").strip()
        if not full_content:
            article["extraction_error"] = "missing full_content"
            logger.warning(
                "Skipping extraction for article without full_content: %s",
                article.get("link", "unknown"),
            )
            return article

        if _extractor is None:
            raise RuntimeError("GLiNER extractor is not initialized in this worker")

        schema_topics = _extractor.create_schema().classification(
            "article_topic",
            TOPIC_LABELS,
            multi_label=True,
            cls_threshold=config.TOPIC_CLS_THRESHOLD,
        )

        article["topics"] = _extractor.extract(
            full_content,
            schema_topics,
            include_confidence=False,
        )["article_topic"]

        schema_entities = _extractor.create_schema().entities(
            ENTITY_LABELS,
            threshold=config.ENTITY_THRESHOLD,
        )

        article["entities"] = _extractor.extract(
            full_content,
            schema_entities,
            include_confidence=False,
        )["entities"]

    except Exception as exc:
        article["extraction_error"] = str(exc)
        logger.exception(
            "Extraction failed for article %s",
            article.get("link", "unknown"),
        )

    return article


def extract_batch(
    executor: ProcessPoolExecutor,
    articles: list[dict[str, Any]],
    batch_number: int,
    total_batches: int,
) -> list[dict[str, Any]]:
    """Run topic and entity extraction on one batch using an existing process pool."""
    if not articles:
        return []

    results = list(
        tqdm(
            executor.map(process_article, articles),
            total=len(articles),
            desc=f"Extracting batch {batch_number}/{total_batches}",
        )
    )

    failed_count = sum(1 for article in results if article.get("extraction_error"))
    if failed_count:
        logger.warning(
            "%d/%d articles in batch %d reported extraction errors.",
            failed_count,
            len(results),
            batch_number,
        )

    return results


def chunk_list(items: list[Any], chunk_size: int) -> list[list[Any]]:
    """Split a list into fixed-size chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def process_and_save_batches(
    s3_client,
    articles: list[dict[str, Any]],
    dest_bucket: str,
    batch_size: int,
    max_workers: int,
    log_file_path: str,
    model_name: str,
    run_date: str,
    run_id: str,
    completed_batches: set[int] | None = None,
    on_batch_saved=None,
) -> list[str]:
    """
    Process articles in batches and save each batch to S3 immediately.

    Saving after each batch means a crash late in the run does not lose earlier work.
    Already-completed batch numbers can be skipped during resume.
    """
    completed_batches = completed_batches or set()
    batches = chunk_list(articles, batch_size)
    saved_keys: list[str] = []

    logger.info(
        "Processing %d articles in %d batches of up to %d articles each.",
        len(articles),
        len(batches),
        batch_size,
    )

    if completed_batches:
        logger.info("Skipping already completed batches: %s", sorted(completed_batches))

    try:
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=init_worker,
            initargs=(log_file_path, model_name),
        ) as executor:
            for batch_number, batch in enumerate(batches, start=1):
                batch_key = build_batch_s3_key(run_date, run_id, batch_number)

                if batch_number in completed_batches:
                    logger.info(
                        "Skipping batch %d/%d (already saved at s3://%s/%s).",
                        batch_number,
                        len(batches),
                        dest_bucket,
                        batch_key,
                    )
                    saved_keys.append(batch_key)
                    continue

                logger.info("Starting batch %d/%d.", batch_number, len(batches))

                try:
                    processed_batch = extract_batch(
                        executor=executor,
                        articles=batch,
                        batch_number=batch_number,
                        total_batches=len(batches),
                    )
                    processed_batch = enrich_and_embed_batch(processed_batch)
                    saved_key = save_batch_to_s3(
                        s3_client=s3_client,
                        articles=processed_batch,
                        bucket=dest_bucket,
                        run_date=run_date,
                        run_id=run_id,
                        batch_number=batch_number,
                    )
                    saved_keys.append(saved_key)

                    if on_batch_saved is not None:
                        on_batch_saved(batch_number, len(batches))

                except S3SaveError:
                    raise
                except EmbeddingError:
                    raise
                except Exception as exc:
                    raise EnrichmentError(
                        f"Unexpected failure while processing batch {batch_number}"
                    ) from exc
    except EnrichmentError:
        raise
    except Exception as exc:
        raise EnrichmentError("Failed to initialize or run the worker process pool") from exc

    return saved_keys
