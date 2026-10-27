from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
REPO_DIR = SRC_DIR.parent


class ReliabilityError(Exception):
    """reliability.json is missing or invalid."""


class NewsClusteringConfig(BaseModel):
    summarize_model: str = "gpt-5-nano"
    fallback_model: Optional[str] = "gpt-5.6"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2

    umap_n_components: int = 50
    umap_n_neighbors: int = 15
    umap_random_state: int = 42
    hdbscan_min_cluster_size: int = 4
    hdbscan_max_cluster_size: int = 30
    hdbscan_min_samples: int = 2

    fuzzy_entity_threshold: int = 50
    reliability_alpha: float = 0.1
    density_k: int = 2
    summary_batch_size: int = 25

    s3_bucket: str
    output_s3_bucket: str
    article_cluster_ids_s3_bucket: str
    aws_region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    openai_api_key: str
    reliability_path: str = "reliability.json"
    job_date: Optional[str] = None

    def resolve_job_date(self) -> str:
        if self.job_date:
            return self.job_date
        return datetime.now(timezone.utc).date().isoformat()

    def resolve_reliability_path(self) -> Path:
        path = Path(self.reliability_path)
        if path.is_file():
            return path.resolve()
        if path.is_absolute():
            raise ReliabilityError(f"reliability file not found: {path}")
        tried = []
        for base in (Path.cwd(), REPO_DIR, SRC_DIR, PACKAGE_DIR):
            candidate = (base / path).resolve()
            tried.append(str(candidate))
            if candidate.is_file():
                return candidate
        raise ReliabilityError("reliability file not found; looked in: " + ", ".join(tried))

    def load_reliabilities(self) -> dict[str, float]:
        path = self.resolve_reliability_path()
        logger.info("Loading source reliabilities from %s", path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReliabilityError(f"reliability file is not valid JSON: {path}") from exc
        if not isinstance(raw, list) or not raw:
            raise ReliabilityError(f"reliability file must be a non-empty list: {path}")
        reliabilities: dict[str, float] = {}
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or "source_name" not in item or "reliability" not in item:
                raise ReliabilityError(
                    f"reliability item {index} must have source_name and reliability: {path}"
                )
            try:
                reliabilities[str(item["source_name"])] = float(item["reliability"])
            except (TypeError, ValueError) as exc:
                raise ReliabilityError(
                    f"reliability item {index} has a non-numeric reliability: {path}"
                ) from exc
        logger.info("Loaded %s source reliability scores", len(reliabilities))
        return reliabilities

    @classmethod
    def from_env(cls) -> NewsClusteringConfig:
        values = {
            "openai_api_key": os.environ["OPENAI_API_KEY"],
            "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
            "aws_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
            "aws_region": os.environ["AWS_REGION"],
            "s3_bucket": os.environ["ENRICHED_ARTICLES_BUCKET"],
            "output_s3_bucket": os.environ["CLUSTERS_BUCKET"],
            "article_cluster_ids_s3_bucket": os.environ["ARTICLE_CLUSTER_IDS_BUCKET"],
        }
        if os.environ.get("NEWS_CLUSTERING_JOB_DATE"):
            values["job_date"] = os.environ["NEWS_CLUSTERING_JOB_DATE"]
        if os.environ.get("NEWS_CLUSTERING_RELIABILITY_PATH"):
            values["reliability_path"] = os.environ["NEWS_CLUSTERING_RELIABILITY_PATH"]
        return cls(**values)
