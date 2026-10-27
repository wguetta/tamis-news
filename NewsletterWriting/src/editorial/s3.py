from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from tqdm import tqdm

from editorial.config import EditorialConfig
from editorial.ranking import attach_cluster_topics

INPUT_BATCH_KEY = re.compile(
    r"^date=(?P<date>\d{4}-\d{2}-\d{2})/run=(?P<run>[^/]+)/batch=\d+\.jsonl$"
)


def make_s3_client(config: EditorialConfig):
    return boto3.client(
        "s3",
        region_name=config.aws_region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )


def list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def read_jsonl_object(s3, bucket: str, key: str) -> list[dict]:
    response = s3.get_object(Bucket=bucket, Key=key)
    rows = []
    for line in response["Body"].iter_lines():
        if line:
            rows.append(json.loads(line))
    return rows


def load_jsonl_prefix(
    s3,
    bucket: str,
    prefix: str,
    name_contains: str | None = None,
    desc: str = "s3 jsonl",
) -> tuple[list[dict], list[str]]:
    keys = [
        key
        for key in sorted(list_keys(s3, bucket, prefix))
        if key.endswith(".jsonl") and (name_contains is None or name_contains in key)
    ]
    rows = []
    for key in tqdm(keys, desc=desc):
        rows.extend(read_jsonl_object(s3, bucket, key))
    return rows, keys


def load_articles(s3, bucket: str, job_date: str) -> tuple[list[dict], dict]:
    prefix = f"date={job_date}/"
    runs: dict[str, list[str]] = defaultdict(list)
    for key in list_keys(s3, bucket, prefix):
        match = INPUT_BATCH_KEY.match(key)
        if match and match.group("date") == job_date:
            runs[match.group("run")].append(key)
    if not runs:
        raise FileNotFoundError(f"No article batches for date={job_date} in s3://{bucket}/{prefix}")
    latest_run = sorted(runs.keys())[-1]
    keys = sorted(runs[latest_run])
    articles = []
    for key in tqdm(keys, desc="s3 articles"):
        articles.extend(read_jsonl_object(s3, bucket, key))
    return articles, {"date": job_date, "run": latest_run, "keys": keys}


def attach_cluster_ids(articles: list[dict], clusters: list[dict], assignments: list[dict]) -> None:
    """Join hashed article↔cluster rows onto articles."""
    id_to_hashed = {}
    for row in assignments:
        article_id = row["article_id"]
        id_to_hashed[article_id] = row["cluster_id"]
        id_to_hashed[str(article_id)] = row["cluster_id"]

    hashed_to_int = {
        cluster["hashed_cluster_id"]: cluster["cluster_id"]
        for cluster in clusters
        if cluster.get("hashed_cluster_id") is not None and "cluster_id" in cluster
    }

    for article in articles:
        article_id = article.get("id", article.get("article_id"))
        hashed = id_to_hashed.get(article_id)
        if hashed is None and article_id is not None:
            hashed = id_to_hashed.get(str(article_id))
        article["hashed_cluster_id"] = hashed
        if hashed in hashed_to_int:
            article["cluster_id"] = hashed_to_int[hashed]


def load_persisted(config: EditorialConfig | None = None, s3=None) -> dict:
    """Load today's persisted articles, cluster summaries, and assignments."""
    config = config or EditorialConfig.from_env()
    s3 = s3 or make_s3_client(config)
    job_date = config.resolve_job_date()
    prefix = f"date={job_date}/"

    articles, article_meta = load_articles(s3, config.articles_s3_bucket, job_date)
    clusters, cluster_keys = load_jsonl_prefix(
        s3,
        config.clusters_s3_bucket,
        prefix,
        name_contains="/batch=",
        desc="s3 clusters",
    )
    assignments, assignment_keys = load_jsonl_prefix(
        s3,
        config.article_cluster_ids_s3_bucket,
        prefix,
        desc="s3 article-cluster ids",
    )
    if not clusters:
        raise FileNotFoundError(f"No persisted clusters for date={job_date}")
    if not assignments:
        raise FileNotFoundError(f"No article-cluster ids for date={job_date}")

    attach_cluster_ids(articles, clusters, assignments)
    attach_cluster_topics(articles, clusters)

    print(f"Loaded date={job_date}: {len(articles)} articles, {len(clusters)} clusters")
    return {
        "job_date": job_date,
        "articles": articles,
        "clusters": clusters,
        "article_meta": article_meta,
        "cluster_keys": cluster_keys,
        "assignment_keys": assignment_keys,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def newsletter_object_key(job_date: str, email: str) -> str:
    if not email or not str(email).strip():
        raise ValueError("Newsletter is missing email")
    safe_email = str(email).strip().replace("/", "_").replace("\\", "_")
    return f"date={job_date}/{safe_email}.jsonl"


def manifest_object_key(job_date: str) -> str:
    return f"date={job_date}/manifest.json"


def email_from_newsletter_key(key: str, job_date: str) -> str | None:
    prefix = f"date={job_date}/"
    if not key.startswith(prefix) or not key.endswith(".jsonl"):
        return None
    name = key[len(prefix) : -len(".jsonl")]
    if not name or "/" in name:
        return None
    return name


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
    body = json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def put_jsonl(s3, bucket: str, key: str, rows: list[dict]) -> None:
    body = (
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n"
    ).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/jsonl")


def load_manifest(s3, bucket: str, job_date: str) -> dict | None:
    return get_json(s3, bucket, manifest_object_key(job_date))


def new_manifest(job_date: str, bucket: str, readers: list[dict] | None = None) -> dict:
    return {
        "date": job_date,
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "bucket": bucket,
        "expected_readers": [reader["email"] for reader in readers or []],
        "newsletter_count": 0,
        "newsletters": [],
        "skipped": [],
    }


def save_manifest(s3, bucket: str, manifest: dict) -> None:
    key = manifest_object_key(manifest["date"])
    put_json(s3, bucket, key, manifest)
    print(f"Wrote manifest s3://{bucket}/{key}")


def existing_reader_emails(s3, bucket: str, job_date: str) -> set[str]:
    emails = set()
    for key in list_keys(s3, bucket, f"date={job_date}/"):
        email = email_from_newsletter_key(key, job_date)
        if email:
            emails.add(email)
    manifest = load_manifest(s3, bucket, job_date)
    for row in (manifest or {}).get("newsletters") or []:
        if row.get("email"):
            emails.add(row["email"])
    return emails


def save_newsletter(s3, bucket: str, job_date: str, newsletter: dict) -> str:
    key = newsletter_object_key(job_date, newsletter.get("email", ""))
    put_jsonl(s3, bucket, key, [newsletter])
    return key


def upsert_manifest_entry(manifest: dict, newsletter: dict, key: str) -> None:
    entry = {
        "email": newsletter["email"],
        "topics": newsletter.get("topics", []),
        "key": key,
        "written_at": utc_now(),
    }
    by_email = {row["email"]: row for row in manifest.get("newsletters") or [] if row.get("email")}
    by_email[newsletter["email"]] = entry
    manifest["newsletters"] = list(by_email.values())
    manifest["newsletter_count"] = len(manifest["newsletters"])


def persist_newsletter(s3, config: EditorialConfig, newsletter: dict, manifest: dict) -> str:
    job_date = config.resolve_job_date()
    bucket = config.newsletters_s3_bucket
    key = save_newsletter(s3, bucket, job_date, newsletter)
    upsert_manifest_entry(manifest, newsletter, key)
    save_manifest(s3, bucket, manifest)
    print(f"Wrote s3://{bucket}/{key}")
    return key


def save_newsletters(
    newsletters: list[dict],
    config: EditorialConfig | None = None,
    s3=None,
    extra: dict | None = None,
) -> dict:
    """Write each reader newsletter as JSONL and merge them into the day's manifest."""
    config = config or EditorialConfig.from_env()
    s3 = s3 or make_s3_client(config)
    job_date = config.resolve_job_date()
    bucket = config.newsletters_s3_bucket
    manifest = load_manifest(s3, bucket, job_date) or new_manifest(job_date, bucket)
    if extra:
        manifest["extra"] = extra
    for newsletter in tqdm(newsletters, desc="s3 newsletters"):
        persist_newsletter(s3, config, newsletter, manifest)
    expected = set(manifest.get("expected_readers") or [])
    written = {row["email"] for row in manifest.get("newsletters") or []}
    if expected and expected <= written:
        manifest["status"] = "success"
    elif written:
        manifest["status"] = "partial" if expected - written else "success"
    else:
        manifest["status"] = "success"
    manifest["finished_at"] = utc_now()
    save_manifest(s3, bucket, manifest)
    return manifest
