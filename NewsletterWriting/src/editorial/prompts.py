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


def cluster_id(cluster: dict) -> int:
    return int(cluster["cluster_id"])


def as_cluster_id(value) -> int:
    return int(value)


def hashed_ids_by_cluster(clusters: list[dict]) -> dict[int, str]:
    return {
        int(cluster["cluster_id"]): cluster["hashed_cluster_id"]
        for cluster in clusters
        if cluster.get("hashed_cluster_id") is not None and "cluster_id" in cluster
    }


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


def attach_hashed_cluster_ids(newsletter: dict, clusters: list[dict]) -> None:
    """Keep hashed IDs on the saved newsletter; writers themselves only use ints."""
    by_id = hashed_ids_by_cluster(clusters)

    def hashed_list(ids) -> list:
        return [by_id.get(as_cluster_id(cid)) for cid in ids]

    def stamp_item(item: dict) -> None:
        item["hashed_cluster_id"] = by_id.get(as_cluster_id(item["cluster_id"]))

    selected = newsletter.get("main_section", {}).get("selected_plan")
    if selected and "clusters" in selected:
        selected["hashed_cluster_ids"] = hashed_list(selected["clusters"])
    for plan in newsletter.get("main_section_candidate_plans") or []:
        plan["hashed_cluster_ids"] = hashed_list(plan.get("clusters") or [])

    for item in newsletter.get("headlines", {}).get("headlines") or []:
        stamp_item(item)
    for item in newsletter.get("candidate_headlines") or []:
        stamp_item(item)
    for item in newsletter.get("stories_to_watch", {}).get("stories_to_watch") or []:
        stamp_item(item)
    for item in newsletter.get("candidate_stories_to_watch") or []:
        stamp_item(item)


def format_articles(texts: list[str]) -> str:
    return "\n\n".join(
        f"================ ARTICLE {i + 1} ================\n\n{text}\n\n"
        f"================ END ARTICLE {i + 1} ================"
        for i, text in enumerate(texts)
    )
