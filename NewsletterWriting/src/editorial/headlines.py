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
            "headlines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "cluster_id": {"type": "integer"},
                        "headline": {"type": "string"},
                        "angle": {"type": "string"},
                    },
                    "required": ["cluster_id", "headline", "angle"],
                },
            }
        },
        "required": ["headlines"],
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
            "headlines": {
                "type": "array",
                "minItems": k,
                "maxItems": k,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "cluster_id": {"type": "integer"},
                        "headline": {"type": "string"},
                        "angle": {"type": "string"},
                        "details": {"type": "string"},
                    },
                    "required": ["cluster_id", "headline", "angle", "details"],
                },
            }
        },
        "required": ["headlines"],
    }


def generate_headlines(
    llm: LlmClient,
    clusters: list[dict],
    articles: list[dict],
    config: EditorialConfig,
    reader_topics: list[str],
):
    prompts = load_prompts("headlines")
    values = config.prompt_values(reader_topics)
    valid_ids = {cluster_id(cluster) for cluster in clusters}

    planned = llm.complete(
        instructions=render(prompts["plan"]["system"], values),
        user=render(prompts["plan"]["user"], {**values, "cluster_input": cluster_input(clusters)}),
        schema=_plan_schema(),
        schema_name="headline_plan",
    )["headlines"]
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
        schema=_select_schema(config.n_headlines),
        schema_name="headline_selection",
    )
    selected = [planned[i] for i in selection["selected_indices"]]
    print("Headlines:", [item["headline"] for item in selected])
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
            f"================ HEADLINE {i + 1} ================\n\n"
            f"CLUSTER ID:\n{item['cluster_id']}\n\nHEADLINE:\n{item['headline']}\n\n"
            f"ANGLE:\n{item['angle']}\n\nREPORTING MATERIAL:\n{article_text}\n\n"
            f"================ END HEADLINE {i + 1} ================"
        )

    written = llm.complete(
        instructions=render(prompts["write"]["system"], values),
        user=render(
            prompts["write"]["user"],
            {**values, "reporting_material": "\n\n".join(blocks)},
        ),
        schema=_write_schema(config.n_headlines),
        schema_name="newsletter_headlines",
    )
    for item in written["headlines"]:
        item["cluster_id"] = as_cluster_id(item["cluster_id"])
    return {
        **written,
        "reason": selection["reason"],
        "candidate_headlines": planned,
    }
