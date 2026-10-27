from __future__ import annotations

import json

from editorial.config import EditorialConfig
from editorial.llm import LlmClient
from editorial.prompts import (
    articles_for_clusters,
    as_cluster_id,
    cluster_id,
    cluster_input,
    load_prompts,
    render,
)


def _plan_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stories_to_watch": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "cluster_id": {"type": "integer"},
                        "headline": {"type": "string"},
                        "watch_for": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["cluster_id", "headline", "watch_for", "confidence"],
                },
            }
        },
        "required": ["stories_to_watch"],
    }


def _select_schema(k: int) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "selected_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": k,
                "maxItems": k,
            },
            "reason": {"type": "string"},
        },
        "required": ["selected_indices", "reason"],
    }


def _write_schema(k: int) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stories_to_watch": {
                "type": "array",
                "minItems": k,
                "maxItems": k,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "cluster_id": {"type": "integer"},
                        "headline": {"type": "string"},
                        "watch_for": {"type": "string"},
                        "confidence": {"type": "string"},
                        "details": {"type": "string"},
                    },
                    "required": ["cluster_id", "headline", "watch_for", "confidence", "details"],
                },
            }
        },
        "required": ["stories_to_watch"],
    }


def generate_stories_to_watch(
    llm: LlmClient,
    clusters: list[dict],
    articles: list[dict],
    config: EditorialConfig,
    reader_topics: list[str],
):
    prompts = load_prompts("stories_to_watch")
    values = config.prompt_values(reader_topics)
    valid_ids = {cluster_id(cluster) for cluster in clusters}

    planned = llm.complete(
        instructions=render(prompts["plan"]["system"], values),
        user=render(prompts["plan"]["user"], {**values, "cluster_input": cluster_input(clusters)}),
        schema=_plan_schema(),
        schema_name="stories_to_watch",
    )["stories_to_watch"]
    for item in planned:
        item["cluster_id"] = as_cluster_id(item["cluster_id"])
        if item["cluster_id"] not in valid_ids:
            raise ValueError(f"Unknown cluster ID: {item['cluster_id']}")

    selection = llm.complete(
        instructions=render(prompts["select"]["system"], values),
        user=render(
            prompts["select"]["user"],
            {
                **values,
                "candidates_json": json.dumps(
                    [{"index": i, **item} for i, item in enumerate(planned)],
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ),
        schema=_select_schema(config.n_stories_to_watch),
        schema_name="story_to_watch_selection",
    )
    selected = [planned[i] for i in selection["selected_indices"]]
    print("Stories to watch:", [item["headline"] for item in selected])
    print(f"Reason: {selection['reason']}")

    blocks = []
    for i, item in enumerate(selected):
        texts = articles_for_clusters(articles, [item["cluster_id"]])
        if not texts:
            raise ValueError(f"No articles for cluster {item['cluster_id']}")
        article_text = "\n\n".join(
            f"---------------- ARTICLE {j + 1} ----------------\n\n{text}\n\n"
            f"---------------- END ARTICLE {j + 1} ----------------"
            for j, text in enumerate(texts)
        )
        blocks.append(
            f"================ STORY {i + 1} ================\n\n"
            f"CLUSTER ID:\n{item['cluster_id']}\n\nHEADLINE:\n{item['headline']}\n\n"
            f"WATCH FOR:\n{item['watch_for']}\n\nCONFIDENCE:\n{item['confidence']}\n\n"
            f"REPORTING MATERIAL:\n{article_text}\n\n"
            f"================ END STORY {i + 1} ================"
        )

    written = llm.complete(
        instructions=render(prompts["write"]["system"], values),
        user=render(
            prompts["write"]["user"],
            {**values, "reporting_material": "\n\n".join(blocks)},
        ),
        schema=_write_schema(config.n_stories_to_watch),
        schema_name="stories_to_watch",
    )
    for item in written["stories_to_watch"]:
        item["cluster_id"] = as_cluster_id(item["cluster_id"])
    return {
        **written,
        "reason": selection["reason"],
        "candidate_stories_to_watch": planned,
    }
