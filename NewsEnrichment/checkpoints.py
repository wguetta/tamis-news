"""S3 checkpoint helpers for Strategy 2 resume support."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

import config
from errors import S3LoadError, S3SaveError

logger = logging.getLogger(__name__)

STAGE_LOAD = "load"
STAGE_ENRICH = "enrich"
STAGE_EXTRACT = "extract"
VALID_FROM_STAGES = {STAGE_LOAD, STAGE_ENRICH, STAGE_EXTRACT}

BATCH_KEY_PATTERN = re.compile(
    r"^date=[^/]+/run=[^/]+/batch=(\d+)\.jsonl$"
)


def generate_run_id(reference: datetime | None = None) -> str:
    """Generate a unique run identifier based on the current UTC time."""
    reference = (reference or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return reference.strftime("%Y%m%dT%H%M%SZ")


def parse_run_date(run_id: str, fallback: datetime) -> str:
    """
    Derive the date partition used for batch output keys.

    Supports run ids like 20260707 or 20260706T211530Z.
    """
    if len(run_id) >= 8 and run_id[:8].isdigit():
        digits = run_id[:8]
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return fallback.astimezone(timezone.utc).strftime("%Y-%m-%d")


def build_log_file_path(run_id: str):
    """Return the per-run log file path."""
    return config.LOG_DIR / f"run-{run_id}.log"


def checkpoint_prefix(run_id: str) -> str:
    return f"checkpoints/run={run_id}/"


def manifest_key(run_id: str) -> str:
    return f"{checkpoint_prefix(run_id)}manifest.json"


def loaded_checkpoint_key(run_id: str) -> str:
    return f"{checkpoint_prefix(run_id)}loaded.jsonl"


def enriched_checkpoint_key(run_id: str) -> str:
    return f"{checkpoint_prefix(run_id)}enriched.jsonl"


def batch_output_prefix(run_date: str, run_id: str) -> str:
    return f"date={run_date}/run={run_id}/"


def s3_object_exists(s3_client, bucket: str, key: str) -> bool:
    """Check whether an object exists without downloading it."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def load_manifest(
    s3_client,
    bucket: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Load the run manifest if it exists."""
    key = manifest_key(run_id)
    if not s3_object_exists(s3_client, bucket, key):
        return None

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except (ClientError, json.JSONDecodeError) as exc:
        raise S3LoadError(f"Failed to read manifest s3://{bucket}/{key}") from exc


def save_manifest(
    s3_client,
    bucket: str,
    manifest: dict[str, Any],
) -> None:
    """Persist the run manifest to S3."""
    run_id = manifest["run_id"]
    key = manifest_key(run_id)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
    except ClientError as exc:
        raise S3SaveError(f"Failed to write manifest s3://{bucket}/{key}") from exc


def create_initial_manifest(
    run_id: str,
    started_at: datetime,
) -> dict[str, Any]:
    """Create a new manifest for a pipeline run."""
    started_at = started_at.astimezone(timezone.utc)
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "updated_at": started_at.isoformat(),
        "run_date": parse_run_date(run_id, started_at),
        "source_hours": config.LOAD_HOURS,
        "total_articles": 0,
        "total_batches": 0,
        "stages": {
            "loaded": "pending",
            "enriched": "pending",
            "extraction": "pending",
        },
        "batches_saved": 0,
    }


def load_checkpoint_jsonl(
    s3_client,
    bucket: str,
    key: str,
) -> list[dict[str, Any]]:
    """Load a JSONL checkpoint file from S3."""
    if not s3_object_exists(s3_client, bucket, key):
        raise S3LoadError(f"Checkpoint not found: s3://{bucket}/{key}")

    articles: list[dict[str, Any]] = []

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        for line in response["Body"].iter_lines():
            if not line:
                continue
            try:
                articles.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid JSON line in s3://%s/%s: %s", bucket, key, exc)
    except ClientError as exc:
        raise S3LoadError(f"Failed to read checkpoint s3://{bucket}/{key}") from exc

    logger.info("Loaded %d articles from s3://%s/%s", len(articles), bucket, key)
    return articles


def save_checkpoint_jsonl(
    s3_client,
    bucket: str,
    key: str,
    articles: list[dict[str, Any]],
) -> None:
    """Save articles as a JSONL checkpoint file to S3."""
    if not articles:
        raise S3SaveError(f"Refusing to save empty checkpoint s3://{bucket}/{key}")

    body = "\n".join(json.dumps(article, ensure_ascii=False) for article in articles)

    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
    except ClientError as exc:
        raise S3SaveError(f"Failed to write checkpoint s3://{bucket}/{key}") from exc

    logger.info("Saved checkpoint with %d articles to s3://%s/%s", len(articles), bucket, key)


def list_completed_batch_numbers(
    s3_client,
    bucket: str,
    run_date: str,
    run_id: str,
) -> set[int]:
    """Return the batch numbers already saved for a run."""
    prefix = batch_output_prefix(run_date, run_id)
    paginator = s3_client.get_paginator("list_objects_v2")
    completed: set[int] = set()

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            match = BATCH_KEY_PATTERN.match(obj["Key"])
            if match:
                completed.add(int(match.group(1)))

    if completed:
        logger.info(
            "Found %d completed batches for run %s: %s",
            len(completed),
            run_id,
            sorted(completed),
        )

    return completed


def is_run_complete(manifest: dict[str, Any], completed_batches: set[int]) -> bool:
    """Return True when extraction finished and all expected batches exist."""
    total_batches = manifest.get("total_batches", 0)
    extraction_status = manifest.get("stages", {}).get("extraction")

    if extraction_status != "completed" or total_batches <= 0:
        return False

    expected = set(range(1, total_batches + 1))
    return expected.issubset(completed_batches)


def resolve_resume_stage(
    s3_client,
    bucket: str,
    run_id: str,
    from_stage: str | None,
) -> str:
    """
    Decide which pipeline stage to start from.

    If from_stage is provided, honor it explicitly.
    Otherwise auto-detect the first incomplete stage from S3 checkpoints.
    """
    if from_stage:
        if from_stage not in VALID_FROM_STAGES:
            raise ValueError(
                f"Invalid from_stage '{from_stage}'. "
                f"Expected one of: {', '.join(sorted(VALID_FROM_STAGES))}"
            )
        return from_stage

    if s3_object_exists(s3_client, bucket, enriched_checkpoint_key(run_id)):
        return STAGE_EXTRACT

    if s3_object_exists(s3_client, bucket, loaded_checkpoint_key(run_id)):
        return STAGE_ENRICH

    return STAGE_LOAD
