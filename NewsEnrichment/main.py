"""
RSS article enrichment entry point.

Run on EC2:
    python main.py
    python main.py --run-id 20260707
    python main.py --run-id 20260707 --from-stage enrich
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import traceback
from datetime import datetime, timezone
from typing import Any

import config
from checkpoints import (
    STAGE_ENRICH,
    STAGE_EXTRACT,
    STAGE_LOAD,
    build_log_file_path,
    create_initial_manifest,
    enriched_checkpoint_key,
    generate_run_id,
    is_run_complete,
    list_completed_batch_numbers,
    load_checkpoint_jsonl,
    load_manifest,
    loaded_checkpoint_key,
    resolve_resume_stage,
    save_checkpoint_jsonl,
    save_manifest,
)
from errors import EmbeddingError, EnrichmentError, PipelineError, S3LoadError, S3SaveError
from pipeline import (
    add_full_content_to_articles,
    enrich_articles_with_contents,
    get_s3_client,
    load_last_n_hours,
    process_and_save_batches,
    remove_duplicates,
)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(processName)s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RSS article enrichment pipeline")
    parser.add_argument(
        "--run-id",
        help="Stable run identifier. Reuse after a crash to resume checkpoints.",
    )
    parser.add_argument(
        "--from-stage",
        choices=[STAGE_LOAD, STAGE_ENRICH, STAGE_EXTRACT],
        help="Force pipeline to start from this stage instead of auto-detecting.",
    )
    return parser.parse_args()


def setup_logging(log_file_path: str) -> None:
    """Configure logging to a per-run file and stdout."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.handlers:
        root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def log_run_configuration(
    logger: logging.Logger,
    run_id: str,
    log_file_path: str,
    resume_stage: str,
) -> None:
    """Log the active configuration at the start of each run."""
    logger.info("Run id: %s", run_id)
    logger.info("Resume stage: %s", resume_stage)
    logger.info("Application directory: %s", config.APP_DIR)
    logger.info("Log file: %s", log_file_path)
    logger.info("Source bucket: %s", config.SOURCE_BUCKET)
    logger.info("Destination bucket: %s", config.DEST_BUCKET)
    logger.info("AWS region: %s", config.AWS_REGION)
    logger.info("Load hours: %s", config.LOAD_HOURS)
    logger.info("Max workers: %s", config.MAX_WORKERS)
    logger.info("Batch size: %s", config.BATCH_SIZE)
    logger.info("Word count limit: %s", config.WORD_COUNT_LIMIT)
    logger.info("GLiNER model: %s", config.GLINER_MODEL)
    logger.info("OpenAI embedding model: %s", config.OPENAI_EMBEDDING_MODEL)


def update_manifest_stage(
    s3_client,
    manifest: dict[str, Any],
    stage_name: str,
    status: str,
) -> None:
    manifest["stages"][stage_name] = status
    save_manifest(s3_client, config.DEST_BUCKET, manifest)


def run_pipeline(run_id: str, from_stage: str | None) -> list[str]:
    """Execute the checkpoint-aware load -> enrich -> extract -> save pipeline."""
    logger = logging.getLogger(__name__)
    run_started_at = datetime.now(timezone.utc)
    s3_client = get_s3_client()
    log_file_path = str(build_log_file_path(run_id))

    resume_stage = resolve_resume_stage(
        s3_client=s3_client,
        bucket=config.DEST_BUCKET,
        run_id=run_id,
        from_stage=from_stage,
    )

    manifest = load_manifest(s3_client, config.DEST_BUCKET, run_id)
    if manifest is None:
        manifest = create_initial_manifest(run_id, run_started_at)
        save_manifest(s3_client, config.DEST_BUCKET, manifest)
        logger.info("Created new manifest for run %s.", run_id)
    else:
        logger.info("Loaded existing manifest for run %s.", run_id)

    run_date = manifest["run_date"]
    completed_batches = list_completed_batch_numbers(
        s3_client=s3_client,
        bucket=config.DEST_BUCKET,
        run_date=run_date,
        run_id=run_id,
    )

    if is_run_complete(manifest, completed_batches) and from_stage is None:
        logger.info("Run %s is already complete. Nothing to do.", run_id)
        return [
            f"date={run_date}/run={run_id}/batch={batch_number:04d}.jsonl"
            for batch_number in sorted(completed_batches)
        ]

    if from_stage in {STAGE_LOAD, STAGE_ENRICH}:
        completed_batches = set()
        logger.info("Forced rerun from '%s': batch skip disabled.", from_stage)

    articles: list[dict[str, Any]] | None = None

    if resume_stage == STAGE_LOAD:
        logger.info("Stage: load + deduplicate from source bucket.")
        update_manifest_stage(s3_client, manifest, "loaded", "in_progress")

        loaded_articles = load_last_n_hours(
            s3_client=s3_client,
            bucket=config.SOURCE_BUCKET,
            n=config.LOAD_HOURS,
        )

        if not loaded_articles:
            logger.warning("No articles loaded. Exiting without processing.")
            update_manifest_stage(s3_client, manifest, "loaded", "completed")
            return []

        articles = remove_duplicates(loaded_articles)

        if not articles:
            logger.warning("No unique articles remain after deduplication. Exiting.")
            update_manifest_stage(s3_client, manifest, "loaded", "completed")
            return []

        save_checkpoint_jsonl(
            s3_client=s3_client,
            bucket=config.DEST_BUCKET,
            key=loaded_checkpoint_key(run_id),
            articles=articles,
        )
        manifest["total_articles"] = len(articles)
        update_manifest_stage(s3_client, manifest, "loaded", "completed")
        resume_stage = STAGE_ENRICH

    if resume_stage == STAGE_ENRICH:
        if articles is None:
            articles = load_checkpoint_jsonl(
                s3_client=s3_client,
                bucket=config.DEST_BUCKET,
                key=loaded_checkpoint_key(run_id),
            )
            manifest["total_articles"] = len(articles)
            manifest["stages"]["loaded"] = "completed"
            save_manifest(s3_client, config.DEST_BUCKET, manifest)

        logger.info("Stage: trafilatura content enrichment.")
        update_manifest_stage(s3_client, manifest, "enriched", "in_progress")

        articles = enrich_articles_with_contents(articles)

        save_checkpoint_jsonl(
            s3_client=s3_client,
            bucket=config.DEST_BUCKET,
            key=enriched_checkpoint_key(run_id),
            articles=articles,
        )
        update_manifest_stage(s3_client, manifest, "enriched", "completed")
        resume_stage = STAGE_EXTRACT

    if resume_stage == STAGE_EXTRACT:
        if from_stage == STAGE_EXTRACT:
            completed_batches = set()
            logger.info("Forced extract stage: reprocessing all batches.")

        articles = load_checkpoint_jsonl(
            s3_client=s3_client,
            bucket=config.DEST_BUCKET,
            key=enriched_checkpoint_key(run_id),
        )
        manifest["stages"]["enriched"] = "completed"
        save_manifest(s3_client, config.DEST_BUCKET, manifest)

        if not articles:
            logger.warning("No articles available for extraction. Exiting.")
            return []

        logger.info("Building truncated full_content fields.")
        articles = add_full_content_to_articles(
            articles,
            word_count_limit=config.WORD_COUNT_LIMIT,
        )

        total_batches = math.ceil(len(articles) / config.BATCH_SIZE)
        manifest["total_articles"] = len(articles)
        manifest["total_batches"] = total_batches
        manifest["stages"]["extraction"] = "in_progress"
        save_manifest(s3_client, config.DEST_BUCKET, manifest)

        logger.info(
            "Stage: GLiNER extraction with %d workers (%d batches).",
            config.MAX_WORKERS,
            total_batches,
        )

        def on_batch_saved(batch_number: int, total: int) -> None:
            manifest["batches_saved"] = batch_number
            manifest["total_batches"] = total
            save_manifest(s3_client, config.DEST_BUCKET, manifest)

        saved_keys = process_and_save_batches(
            s3_client=s3_client,
            articles=articles,
            dest_bucket=config.DEST_BUCKET,
            batch_size=config.BATCH_SIZE,
            max_workers=config.MAX_WORKERS,
            log_file_path=log_file_path,
            model_name=config.GLINER_MODEL,
            run_date=run_date,
            run_id=run_id,
            completed_batches=completed_batches,
            on_batch_saved=on_batch_saved,
        )

        manifest["batches_saved"] = total_batches
        update_manifest_stage(s3_client, manifest, "extraction", "completed")

        logger.info(
            "Pipeline completed successfully. Saved %d batches.",
            len(saved_keys),
        )
        for key in saved_keys:
            logger.info("Output object: s3://%s/%s", config.DEST_BUCKET, key)

        return saved_keys

    raise EnrichmentError(f"Unsupported resume stage: {resume_stage}")


def main() -> int:
    """Application entry point."""
    args = parse_args()
    run_id = args.run_id or generate_run_id()
    log_file_path = str(build_log_file_path(run_id))

    setup_logging(log_file_path)
    logger = logging.getLogger(__name__)

    resume_stage = args.from_stage or "auto"
    log_run_configuration(logger, run_id, log_file_path, resume_stage)
    logger.info("Starting RSS enrichment pipeline.")

    try:
        saved_keys = run_pipeline(run_id=run_id, from_stage=args.from_stage)
        if not saved_keys:
            logger.info("Pipeline finished with no output batches.")
        return 0

    except S3LoadError:
        logger.exception("Failed while loading source data or checkpoints from S3.")
        return 1
    except S3SaveError:
        logger.exception("Failed while saving checkpoints or batches to S3.")
        return 1
    except EnrichmentError:
        logger.exception("Failed during article enrichment or extraction.")
        return 1
    except EmbeddingError:
        logger.exception("Failed while generating OpenAI embeddings.")
        return 1
    except PipelineError:
        logger.exception("Pipeline failed.")
        return 1
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
        return 130
    except Exception:
        logger.error("Unexpected failure:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
