from __future__ import annotations

import json

from editorial.config import EditorialConfig
from editorial.llm import LlmClient
from editorial.prompts import (
    articles_for_clusters,
    as_cluster_id,
    cluster_id,
    cluster_input,
    format_articles,
    load_prompts,
    render,
)


def _plan_schema(n: int) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sections": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "section_title": {"type": "string"},
                        "clusters": {"type": "array", "items": {"type": "string"}},
                        "editorial_theme": {"type": "string"},
                        "questions": {"type": "string"},
                    },
                    "required": ["section_title", "clusters", "editorial_theme", "questions"],
                },
            }
        },
        "required": ["sections"],
    }


def _select_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "selected_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
                "maxItems": 1,
            },
            "reason": {"type": "string"},
        },
        "required": ["selected_indices", "reason"],
    }


WRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"],
}


def write_main_section(
    llm: LlmClient,
    clusters: list[dict],
    articles: list[dict],
    config: EditorialConfig,
    reader_topics: list[str],
):
    prompts = load_prompts("main_section")
    values = config.prompt_values(reader_topics)
    valid_ids = {cluster_id(cluster) for cluster in clusters}

    plans = llm.complete(
        instructions=render(prompts["plan"]["system"], values),
        user=render(prompts["plan"]["user"], {**values, "cluster_input": cluster_input(clusters)}),
        schema=_plan_schema(config.n_section_plans),
        schema_name="newsletter_editorial_plan",
    )["sections"]
    for plan in plans:
        plan["clusters"] = [as_cluster_id(cid) for cid in plan["clusters"]]
        unknown = set(plan["clusters"]) - valid_ids
        if unknown:
            raise ValueError(f"Unknown cluster IDs: {unknown}")

    selection = llm.complete(
        instructions=render(prompts["select"]["system"], values),
        user=render(
            prompts["select"]["user"],
            {
                **values,
                "candidates_json": json.dumps(
                    [{"index": i, **plan} for i, plan in enumerate(plans)],
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ),
        schema=_select_schema(),
        schema_name="main_section_plan_selection",
    )
    plan = plans[selection["selected_indices"][0]]
    print(f"Main section: {plan['section_title']}")
    print(f"Reason: {selection['reason']}")

    texts = articles_for_clusters(articles, plan["clusters"])
    if not texts:
        raise ValueError(f"No articles for clusters {plan['clusters']}")

    written = llm.complete(
        instructions=render(prompts["write"]["system"], values),
        user=render(
            prompts["write"]["user"],
            {
                **values,
                "section_context": json.dumps(plan, ensure_ascii=False, indent=2),
                "reporting_material": format_articles(texts),
            },
        ),
        schema=WRITE_SCHEMA,
        schema_name="newsletter_section",
    )
    return {
        **written,
        "selected_plan": plan,
        "reason": selection["reason"],
        "candidate_plans": plans,
    }
