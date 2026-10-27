from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


def format_topic_list(topics: list[str]) -> str:
    readable = [topic.replace("_", " ") for topic in topics]
    if not readable:
        return "general news"
    if len(readable) == 1:
        return readable[0]
    if len(readable) == 2:
        return f"{readable[0]} and {readable[1]}"
    return ", ".join(readable[:-1]) + f", and {readable[-1]}"


class EditorialConfig(BaseModel):
    n_section_plans: int = 4
    main_section_min_words: int = 200
    main_section_max_words: int = 400

    n_headlines_plan_min: int = 5
    n_headlines_plan_max: int = 10
    n_headlines: int = 3
    headline_details_words: int = 50
    headline_title_min_words: int = 6
    headline_title_max_words: int = 14

    n_stories_plan_min: int = 4
    n_stories_plan_max: int = 8
    n_stories_to_watch: int = 3
    story_details_words: int = 50

    top_n_by_story: int = 100
    top_n_by_reader: int = 20

    editorial_model: str = "gpt-5.6-luna"
    fallback_model: Optional[str] = "gpt-5.6"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2

    articles_s3_bucket: str = ""
    clusters_s3_bucket: str = ""
    article_cluster_ids_s3_bucket: str = ""
    newsletters_s3_bucket: str = ""
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    openai_api_key: str = ""
    job_date: Optional[str] = None
    readers_path: str = "readers.json"

    def resolve_job_date(self) -> str:
        if self.job_date:
            return self.job_date
        return datetime.now(timezone.utc).date().isoformat()

    def load_readers(self) -> list[dict]:
        path = Path(self.readers_path)
        readers = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(readers, list) or not readers:
            raise ValueError(f"{path} must be a non-empty list of readers")
        for index, reader in enumerate(readers):
            if not reader.get("email"):
                raise ValueError(f"Reader {index} is missing email")
            if not reader.get("topics"):
                raise ValueError(f"Reader {index} is missing topics")
        return readers

    def prompt_values(self, reader_topics: list[str]) -> dict:
        return {
            "reader_topics_text": format_topic_list(reader_topics),
            "n_section_plans": self.n_section_plans,
            "main_section_min_words": self.main_section_min_words,
            "main_section_max_words": self.main_section_max_words,
            "n_headlines_plan_min": self.n_headlines_plan_min,
            "n_headlines_plan_max": self.n_headlines_plan_max,
            "n_headlines": self.n_headlines,
            "headline_details_words": self.headline_details_words,
            "headline_title_min_words": self.headline_title_min_words,
            "headline_title_max_words": self.headline_title_max_words,
            "n_stories_plan_min": self.n_stories_plan_min,
            "n_stories_plan_max": self.n_stories_plan_max,
            "n_stories_to_watch": self.n_stories_to_watch,
            "story_details_words": self.story_details_words,
        }

    @classmethod
    def from_env(cls) -> EditorialConfig:
        values = {
            "openai_api_key": os.environ["OPENAI_API_KEY"],
            "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
            "aws_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
            "aws_region": os.environ["AWS_REGION"],
            "articles_s3_bucket": os.environ["ENRICHED_ARTICLES_BUCKET"],
            "clusters_s3_bucket": os.environ["CLUSTERS_BUCKET"],
            "article_cluster_ids_s3_bucket": os.environ["ARTICLE_CLUSTER_IDS_BUCKET"],
            "newsletters_s3_bucket": os.environ["NEWSLETTERS_BUCKET"],
        }
        if os.environ.get("EDITORIAL_JOB_DATE"):
            values["job_date"] = os.environ["EDITORIAL_JOB_DATE"]
        if os.environ.get("EDITORIAL_READERS_PATH"):
            values["readers_path"] = os.environ["EDITORIAL_READERS_PATH"]
        return cls(**values)
