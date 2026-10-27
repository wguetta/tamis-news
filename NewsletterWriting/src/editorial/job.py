from __future__ import annotations

import argparse
import re
from typing import Optional

from editorial.config import EditorialConfig
from editorial.llm import LlmClient
from editorial.mail import send_reader_newsletter
from editorial.newsletter import write_for_reader
from editorial.ranking import top_clusters_by_story_score
from editorial.s3 import (
    existing_reader_emails,
    load_manifest,
    load_persisted,
    make_s3_client,
    new_manifest,
    newsletter_object_key,
    persist_newsletter,
    save_manifest,
    utc_now,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def pending_readers(readers: list[dict], already_written: set[str]) -> list[dict]:
    return [reader for reader in readers if reader["email"] not in already_written]


def run_newsletters(config: EditorialConfig, s3=None, llm: LlmClient | None = None) -> dict:
    config.job_date = config.resolve_job_date()
    job_date = config.job_date
    s3 = s3 or make_s3_client(config)
    bucket = config.newsletters_s3_bucket
    readers = config.load_readers()
    already = existing_reader_emails(s3, bucket, job_date)
    pending = pending_readers(readers, already)
    skipped = [reader["email"] for reader in readers if reader["email"] in already]

    print(
        f"Date {job_date}: {len(already)} newsletter(s) already in s3://{bucket}/date={job_date}/, "
        f"{len(pending)} remaining"
    )
    for email in skipped:
        print(f"Skipping {email}")

    manifest = load_manifest(s3, bucket, job_date) or new_manifest(job_date, bucket, readers)
    manifest["status"] = "running"
    manifest["expected_readers"] = [reader["email"] for reader in readers]
    manifest["skipped"] = skipped
    if not manifest.get("started_at"):
        manifest["started_at"] = utc_now()
    known = {row.get("email") for row in manifest.get("newsletters") or []}
    for email in skipped:
        if email not in known:
            (manifest.setdefault("newsletters", [])).append(
                {
                    "email": email,
                    "key": newsletter_object_key(job_date, email),
                    "already_present": True,
                }
            )
    manifest["newsletter_count"] = len(manifest.get("newsletters") or [])
    save_manifest(s3, bucket, manifest)

    wrote: list[str] = []
    if not pending:
        manifest["status"] = "success"
        manifest["finished_at"] = utc_now()
        save_manifest(s3, bucket, manifest)
        print(f"Nothing to write for date={job_date}")
        return {
            "job_date": job_date,
            "wrote": wrote,
            "skipped": skipped,
            "manifest": manifest,
        }

    loaded = load_persisted(config, s3)
    clusters = top_clusters_by_story_score(loaded["clusters"], config.top_n_by_story)
    articles = loaded["articles"]
    llm = llm or LlmClient(config)

    try:
        for reader in pending:
            newsletter = write_for_reader(llm, reader, clusters, articles, config)
            send_reader_newsletter(newsletter)
            persist_newsletter(s3, config, newsletter, manifest)
            wrote.append(reader["email"])
        written = existing_reader_emails(s3, bucket, job_date)
        expected = set(manifest["expected_readers"])
        manifest["status"] = "success" if expected <= written else "partial"
        manifest["finished_at"] = utc_now()
        save_manifest(s3, bucket, manifest)
    except Exception:
        manifest["status"] = "failed"
        manifest["finished_at"] = utc_now()
        try:
            save_manifest(s3, bucket, manifest)
        except Exception:
            print("Could not write failed manifest")
        raise

    print(
        f"Finished date={job_date} status={manifest['status']}: "
        f"wrote {len(wrote)}, skipped {len(skipped)}"
    )
    return {
        "job_date": job_date,
        "wrote": wrote,
        "skipped": skipped,
        "manifest": manifest,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write and persist reader newsletters")
    parser.add_argument(
        "--date",
        help="Job date YYYY-MM-DD (UTC today if omitted)",
    )
    args = parser.parse_args(argv)
    if args.date and not DATE_RE.fullmatch(args.date):
        parser.error("--date must be YYYY-MM-DD")

    config = EditorialConfig.from_env()
    if args.date:
        config = config.model_copy(update={"job_date": args.date})

    try:
        result = run_newsletters(config)
    except Exception as exc:
        print(f"Newsletter job failed: {exc}")
        return 1
    return 0 if result["manifest"]["status"] in {"success", "partial"} else 1
