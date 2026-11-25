from __future__ import annotations

from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompts(name: str) -> dict:
    return yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def render(template: str, values: dict) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def as_cluster_id(value):
    """Keep dated ids like 20261112-282 as strings. Plain integers stay integers."""
    if isinstance(value, bool):
        raise ValueError(f"Invalid cluster id: {value}")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def cluster_id(cluster: dict):
    return as_cluster_id(cluster["cluster_id"])


def cluster_input(clusters: list[dict]) -> str:
    blocks = []
    for cluster in clusters:
        cid = cluster_id(cluster)
        blocks.append(
            f"================ CLUSTER {cid} ================\n\n"
            f"{cluster['summary']}\n\n"
            f"================ END CLUSTER {cid} ================"
        )
    return "\n\n".join(blocks)


def articles_for_clusters(articles: list[dict], cluster_ids) -> list[str]:
    wanted = {as_cluster_id(cid) for cid in cluster_ids}
    texts = []
    for article in articles:
        raw = article.get("cluster_id")
        if raw is None or not article.get("full_content"):
            continue
        if as_cluster_id(raw) in wanted:
            texts.append(article["full_content"])
    return texts


def format_articles(texts: list[str]) -> str:
    return "\n\n".join(
        f"================ ARTICLE {i + 1} ================\n\n{text}\n\n"
        f"================ END ARTICLE {i + 1} ================"
        for i, text in enumerate(texts)
    )
