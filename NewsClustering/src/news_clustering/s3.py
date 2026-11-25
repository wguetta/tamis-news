from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from news_clustering.clustering import format_cluster_id, is_noise_cluster_id
from news_clustering.config import NewsClusteringConfig

logger = logging.getLogger(__name__)

INPUT_BATCH_KEY = re.compile(
    r"^date=(?P<date>\d{4}-\d{2}-\d{2})/run=(?P<run>[^/]+)/batch=\d+\.jsonl$"
)


class S3LoadError(Exception):
    """Input S3 data is missing, incomplete, or not for today's job date."""


def make_s3_client(config: NewsClusteringConfig):
    return boto3.client(
        "s3",
        region_name=config.aws_region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )


def parse_input_key(key: str) -> Optional[Tuple[str, str]]:
    match = INPUT_BATCH_KEY.match(key)
    if not match:
        return None
    return match.group("date"), match.group("run")


def output_batch_key(job_date: str, batch_index: int) -> str:
    return f"date={job_date}/batch={batch_index:03d}.jsonl"


def noise_key(job_date: str) -> str:
    return f"date={job_date}/noise.jsonl"


def article_cluster_rows(articles: list[dict], clusters: list[dict]) -> list[dict]:
    rows = []
    for cluster in clusters:
        cluster_id = cluster.get("cluster_id")
        if not cluster_id:
            continue
        article_ids = cluster.get("article_ids") or []
        if article_ids:
            for article_id in article_ids:
                if article_id is not None:
                    rows.append({"article_id": article_id, "cluster_id": cluster_id})
            continue
        for article in articles:
            if article.get("cluster_id") != cluster_id:
                continue
            article_id = article.get("id", article.get("article_id"))
            if article_id is not None:
                rows.append({"article_id": article_id, "cluster_id": cluster_id})
    return rows


def noise_article_rows(articles: list[dict], job_date: str, noise_article_ids=None) -> list[dict]:
    noise_id = format_cluster_id(job_date, -1)
    if noise_article_ids is not None:
        wanted = set(noise_article_ids)
        selected = [article for article in articles if article.get("id") in wanted]
    else:
        selected = [article for article in articles if is_noise_cluster_id(article.get("cluster_id"))]
    return [
        {"article_id": article["id"], "cluster_id": noise_id}
        for article in selected
        if article.get("id") is not None
    ]


def manifest_key(job_date: str) -> str:
    return f"checkpoints/date={job_date}/manifest.json"


def ranked_checkpoint_key(job_date: str) -> str:
    return f"checkpoints/date={job_date}/ranked_clusters.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def check_s3_date(loaded_date: str, expected_date: str) -> None:
    if loaded_date != expected_date:
        raise S3LoadError(
            f"S3 partition date {loaded_date} does not match job date {expected_date}"
        )


def check_s3_load(articles: list[dict], keys: list[str]) -> None:
    if not keys:
        raise S3LoadError("S3 listing returned no batch objects")
    if not articles:
        raise S3LoadError(f"S3 batches contained no articles: {keys}")
    missing = [
        index
        for index, article in enumerate(articles)
        if not article.get("embedding_vector")
    ]
    if missing:
        raise S3LoadError(
            f"{len(missing)} articles are missing embedding_vector "
            f"(first index {missing[0]})"
        )
    logger.info("S3 load check passed: %s articles from %s batch files", len(articles), len(keys))


def select_todays_run(keys: list[str], expected_date: str) -> tuple[str, list[str]]:
    runs: dict[str, list[str]] = defaultdict(list)
    mismatches = []
    for key in keys:
        parsed = parse_input_key(key)
        if parsed is None:
            logger.info("Skipping non-batch object %s", key)
            continue
        date, run = parsed
        if date != expected_date:
            mismatches.append(key)
            continue
        runs[run].append(key)
    if mismatches:
        raise S3LoadError(
            f"Found {len(mismatches)} objects whose date is not {expected_date}: "
            f"{mismatches[:5]}"
        )
    if not runs:
        raise S3LoadError(
            f"No input batch files for date={expected_date} in the listed prefix"
        )
    latest_run = sorted(runs.keys())[-1]
    batch_keys = sorted(runs[latest_run])
    logger.info("Selected input run %s (%s batches) for date=%s", latest_run, len(batch_keys), expected_date)
    return latest_run, batch_keys


def _read_jsonl_object(s3, bucket: str, key: str) -> list[dict]:
    response = s3.get_object(Bucket=bucket, Key=key)
    articles = []
    for line_number, line in enumerate(response["Body"].iter_lines(), start=1):
        if not line:
            continue
        try:
            articles.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise S3LoadError(f"Invalid JSONL in s3://{bucket}/{key} line {line_number}") from exc
    return articles


def load_articles(config: NewsClusteringConfig, s3=None) -> tuple[list[dict], dict]:
    s3 = s3 or make_s3_client(config)
    job_date = config.resolve_job_date()
    prefix = f"date={job_date}/"
    logger.info("Listing input articles at s3://%s/%s", config.s3_bucket, prefix)
    try:
        listed = list_keys(s3, config.s3_bucket, prefix)
    except ClientError as exc:
        raise S3LoadError(f"Failed to list s3://{config.s3_bucket}/{prefix}: {exc}") from exc
    if not listed:
        raise S3LoadError(f"No objects found for today's date s3://{config.s3_bucket}/{prefix}")

    latest_run, batch_keys = select_todays_run(listed, job_date)

    articles = []
    for key in batch_keys:
        logger.info("Reading %s", key)
        try:
            articles.extend(_read_jsonl_object(s3, config.s3_bucket, key))
        except ClientError as exc:
            raise S3LoadError(f"Failed to read s3://{config.s3_bucket}/{key}: {exc}") from exc

    loaded_date = parse_input_key(batch_keys[0])[0]
    check_s3_date(loaded_date, job_date)
    logger.info("Verified loaded S3 date %s is the job date", loaded_date)
    check_s3_load(articles, batch_keys)
    meta = {"date": loaded_date, "run": latest_run, "keys": batch_keys}
    logger.info("Loaded %s articles from run %s on date %s", len(articles), latest_run, loaded_date)
    return articles, meta


def get_json(s3, bucket: str, key: str):
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404"}:
            return None
        raise
    return json.loads(response["Body"].read())


def put_json(s3, bucket: str, key: str, payload) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    logger.info("Wrote s3://%s/%s", bucket, key)


def put_jsonl(s3, bucket: str, key: str, rows: list[dict]) -> None:
    body = ("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n").encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/jsonl")
    logger.info("Wrote %s records to s3://%s/%s", len(rows), bucket, key)


def load_manifest(s3, bucket: str, job_date: str) -> Optional[dict]:
    return get_json(s3, bucket, manifest_key(job_date))


def save_manifest(s3, bucket: str, manifest: dict) -> None:
    put_json(s3, bucket, manifest_key(manifest["date"]), manifest)


def persistable_cluster(cluster: dict, extra_skip=()) -> dict:
    skip = {"articles", *extra_skip}
    return {key: value for key, value in cluster.items() if key not in skip}


def save_ranked_checkpoint(s3, bucket: str, job_date: str, clusters: list[dict]) -> str:
    key = ranked_checkpoint_key(job_date)
    put_json(s3, bucket, key, [persistable_cluster(cluster) for cluster in clusters])
    return key


def load_ranked_checkpoint(s3, bucket: str, job_date: str) -> Optional[List[dict]]:
    payload = get_json(s3, bucket, ranked_checkpoint_key(job_date))
    if payload is None:
        return None
    if not isinstance(payload, list):
        raise S3LoadError(f"Ranked checkpoint is not a list: {ranked_checkpoint_key(job_date)}")
    return payload


def save_cluster_batch(s3, bucket: str, job_date: str, batch_index: int, clusters: list[dict]) -> str:
    key = output_batch_key(job_date, batch_index)
    put_jsonl(
        s3,
        bucket,
        key,
        [persistable_cluster(cluster, extra_skip=("article_ids", "titles")) for cluster in clusters],
    )
    return key


def save_article_cluster_batch(
    s3, bucket: str, job_date: str, batch_index: int, rows: list[dict]
) -> str:
    key = output_batch_key(job_date, batch_index)
    put_jsonl(s3, bucket, key, rows)
    return key


def save_noise_article_cluster_ids(s3, bucket: str, job_date: str, rows: list[dict]) -> str:
    key = noise_key(job_date)
    put_jsonl(s3, bucket, key, rows)
    return key
