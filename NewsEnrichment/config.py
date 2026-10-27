"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

# Directory containing this package (and main.py). Logs are written here.
APP_DIR = Path(__file__).resolve().parent


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


AWS_ACCESS_KEY_ID = _required("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = _required("AWS_SECRET_ACCESS_KEY")
AWS_REGION = _required("AWS_REGION")
OPENAI_API_KEY = _required("OPENAI_API_KEY")
SOURCE_BUCKET = _required("UNIQUE_ARTICLES_BUCKET")
DEST_BUCKET = _required("ENRICHED_ARTICLES_BUCKET")

# Pipeline tuning — override via environment variables on EC2 without code changes.
LOAD_HOURS = int(os.getenv("LOAD_HOURS", "24"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
WORD_COUNT_LIMIT = int(os.getenv("WORD_COUNT_LIMIT", "200"))
MIN_CONTENT_LENGTH = int(os.getenv("MIN_CONTENT_LENGTH", "200"))

GLINER_MODEL = os.getenv("GLINER_MODEL", "fastino/gliner2-base-v1")

OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
OPENAI_RETRY_BASE_DELAY_SECONDS = float(os.getenv("OPENAI_RETRY_BASE_DELAY_SECONDS", "2"))

LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# GLiNER extraction thresholds.
TOPIC_CLS_THRESHOLD = 0.7
ENTITY_THRESHOLD = 0.7
