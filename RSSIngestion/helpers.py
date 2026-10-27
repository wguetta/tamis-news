import calendar
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests
#import trafilatura
import hashlib


DEFAULT_FEEDS_PATH = Path(__file__).resolve().parent / "feeds.json"
REQUEST_TIMEOUT_SECONDS = 15
RECENT_STORY_WINDOW = timedelta(hours=24)

def load_feed_urls(feeds_path: str | Path | None = None) -> list[dict[str, str]]:
    """Load RSS feed definitions from the JSON config file."""
    path = Path(feeds_path) if feeds_path else DEFAULT_FEEDS_PATH

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    feeds = data.get("feeds", [])
    if not isinstance(feeds, list):
        raise ValueError("feeds.json must contain a 'feeds' array")

    validated: list[dict[str, str]] = []
    for index, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            raise ValueError(f"Feed entry at index {index} must be an object")

        name = feed.get("name")
        url = feed.get("url")
        if not name or not url:
            raise ValueError(f"Feed entry at index {index} requires 'name' and 'url'")

        validated.append({"name": str(name), "url": str(url)})

    return validated


def fetch_feed_xml(url: str) -> str:
    """Download raw RSS/Atom XML from a feed URL."""
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "rss-news-lambda/1.0"},
    )
    response.raise_for_status()
    return response.text


def get_entry_published_at(entry: dict[str, Any]) -> datetime | None:
    """Return the entry publish time as a UTC datetime, if available."""
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed_time:
        return None

    return datetime.fromtimestamp(calendar.timegm(parsed_time), tz=timezone.utc)


def is_recent_entry(entry: dict[str, Any], window: timedelta = RECENT_STORY_WINDOW) -> bool:
    """Return True when an entry has a publish date within the given window."""
    published_at = get_entry_published_at(entry)
    if published_at is None:
        return False

    now = datetime.now(timezone.utc)
    cutoff = now - window
    return cutoff <= published_at <= now


def parse_story(entry: dict[str, Any], source_name: str) -> dict[str, Any]:
    """Normalize a single feed entry into a consistent story shape."""
    published = entry.get("published") or entry.get("updated")

    return {
        "source": source_name,
        "title": entry.get("title", "").strip(),
        "link": entry.get("link", "").strip(),
        "description": (entry.get("description") or entry.get("summary") or "").strip(),
        "author": entry.get("author", "").strip(),
        "published": published,
        "id": entry.get("id") or entry.get("link") or entry.get("title"),
    }


def extract_stories_from_feed(feed_name: str, feed_url: str) -> list[dict[str, Any]]:
    """Fetch and parse all stories from one RSS feed."""
    xml_content = fetch_feed_xml(feed_url)
    parsed = feedparser.parse(xml_content)

    if parsed.bozo and not parsed.entries:
        message = str(parsed.bozo_exception) if parsed.bozo_exception else "Invalid feed"
        raise ValueError(f"Failed to parse feed '{feed_name}': {message}")

    return [parse_story(entry, feed_name) for entry in parsed.entries if is_recent_entry(entry)]


def extract_all_stories(
    feeds_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """
    Extract stories from every configured feed.

    Returns a tuple of (stories, errors). Errors contain feed metadata for
    feeds that failed without stopping processing of the remaining feeds.
    """
    feeds = load_feed_urls(feeds_path)
    stories: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for feed in feeds:
        try:
            stories.extend(extract_stories_from_feed(feed["name"], feed["url"]))
        except Exception as exc:
            errors.append(
                {
                    "name": feed["name"],
                    "url": feed["url"],
                    "error": str(exc),
                }
            )

    return stories, errors


def build_response(stories: list[dict[str, Any]], errors: list[dict[str, str]]) -> dict[str, Any]:
    """Build the Lambda response payload."""
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "story_count": len(stories),
        "error_count": len(errors),
        "stories": stories,
        "errors": errors,
    }


def get_feeds_path_from_env() -> str | None:
    """Allow overriding the feeds JSON path via environment variable."""
    return os.environ.get("FEEDS_JSON_PATH")


def validate_rss_url(url: str, name: str | None = None) -> dict[str, Any]:
    """
    Test whether an RSS/Atom URL is reachable and parseable.

    Use this before adding a new feed to feeds.json. Returns a structured report
    instead of raising, so it is safe for routine manual checks.
    """
    feed_name = name or url
    report: dict[str, Any] = {
        "valid": False,
        "url": url,
        "name": feed_name,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "http_status": None,
        "feed_title": "",
        "feed_description": "",
        "entry_count": 0,
        "parse_warning": None,
        "sample_stories": [],
        "error": None,
    }

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "rss-news-lambda/1.0"},
        )
        report["http_status"] = response.status_code
        response.raise_for_status()

        parsed = feedparser.parse(response.text)
        report["feed_title"] = (parsed.feed.get("title") or "").strip()
        report["feed_description"] = (parsed.feed.get("description") or "").strip()
        report["entry_count"] = len(parsed.entries)

        if parsed.bozo and parsed.bozo_exception:
            report["parse_warning"] = str(parsed.bozo_exception)

        if not parsed.entries:
            report["error"] = report["parse_warning"] or "Feed returned no entries"
            return report

        stories = [parse_story(entry, feed_name) for entry in parsed.entries[:3]]
        report["sample_stories"] = stories
        report["valid"] = True
        return report

    except requests.RequestException as exc:
        report["error"] = f"HTTP request failed: {exc}"
        return report
    except Exception as exc:
        report["error"] = str(exc)
        return report


def format_validation_report(report: dict[str, Any]) -> str:
    """Format a validation report for terminal output."""
    lines = [
        f"Feed: {report['name']}",
        f"URL: {report['url']}",
        f"Checked: {report['checked_at']}",
        f"Valid: {'yes' if report['valid'] else 'no'}",
    ]

    if report["http_status"] is not None:
        lines.append(f"HTTP status: {report['http_status']}")

    if report["feed_title"]:
        lines.append(f"Feed title: {report['feed_title']}")

    if report["feed_description"]:
        lines.append(f"Description: {report['feed_description'][:120]}")

    lines.append(f"Entries found: {report['entry_count']}")

    if report["parse_warning"]:
        lines.append(f"Parse warning: {report['parse_warning']}")

    if report["error"]:
        lines.append(f"Error: {report['error']}")

    for index, story in enumerate(report["sample_stories"], start=1):
        lines.append(f"Sample {index}: {story['title']}")
        if story["link"]:
            lines.append(f"  {story['link']}")

    return "\n".join(lines)

def load_hour(
    bucket: str,
    dt: datetime,
) -> list[dict]:
    """
    Load all stories for a given UTC hour.

    Example:
    load_hour(bucket="news-raw", dt=datetime(2026, 6, 23, 14))
    """

    prefix = (
        f"date={dt:%Y-%m-%d}/"
        f"hour={dt:%H}/"
    )

    stories = []

    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=bucket,
        Prefix=prefix,
    ):
        for obj in page.get("Contents", []):

            response = s3.get_object(
                Bucket=bucket,
                Key=obj["Key"],
            )

            for line in response["Body"].iter_lines():
                stories.append(json.loads(line))

    return stories

def load_latest_file(s3_client, bucket: str) -> list[dict[str, Any]]:
    """
    Load stories from the most recently modified JSONL file in the bucket.
    """

    paginator = s3_client.get_paginator("list_objects_v2")

    latest_obj = None

    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]

            if not key.endswith(".jsonl"):
                continue

            if (
                latest_obj is None
                or obj["LastModified"] > latest_obj["LastModified"]
            ):
                latest_obj = obj

    if latest_obj is None:
        return []
    
    print(latest_obj["Key"])

    response = s3_client.get_object(
        Bucket=bucket,
        Key=latest_obj["Key"],
    )

    stories: list[dict[str, Any]] = []

    for line in response["Body"].iter_lines():
        if line:
            stories.append(json.loads(line))

    return stories

def get_new_articles(current_rss_articles, previous_rss_articles):

    previous_titles = set(article["title"] for article in previous_rss_articles)

    new_articles = [
        article
        for article in current_rss_articles
        if article["title"] not in previous_titles
    ]

    return new_articles


def remove_duplicates(articles):

    unique_articles = {}

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
    
    return list(unique_articles.values())

def generate_unique_ids(articles): 

    for article in articles:
        article["id"] = hashlib.sha256(article["title"].encode()).hexdigest()

    return articles
    
def build_s3_key(dt: datetime) -> str:
    """
    Example:
    date=2026-06-23/hour=14/stories.jsonl
    """

    dt = dt.astimezone(timezone.utc)

    return (
        f"date={dt:%Y-%m-%d}/"
        f"hour={dt:%H}/"
        f"{dt:%Y%m%dT%H%M%SZ}.jsonl"
    )


def save_data_to_s3(
    s3_client,
    articles: list[dict],
    bucket: str,
    dt: datetime | None = None,
) -> str:
    """
    Save articles as JSONL to S3.

    Returns the S3 key written.
    """

    #dt = dt or datetime.now(timezone.utc)

    key = build_s3_key(dt)

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

    return key

