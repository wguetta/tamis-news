"""Build enriched content strings and generate OpenAI embeddings."""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import APIError, APIStatusError, OpenAI, RateLimitError

import config
from errors import EmbeddingError
from schemas import TOPIC_DISPLAY_NAMES

logger = logging.getLogger(__name__)

_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """Return a shared OpenAI client."""
    global _openai_client

    if not config.OPENAI_API_KEY:
        raise EmbeddingError("OPENAI_API_KEY is not configured.")

    if _openai_client is None:
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

    return _openai_client


def format_topics_for_enriched_content(topics: list[str] | None) -> str:
    """Format topic labels for the enriched content string."""
    if not topics:
        return ""

    display_names = [
        TOPIC_DISPLAY_NAMES.get(topic, topic.replace("_", " ").title())
        for topic in topics
    ]
    return ", ".join(display_names)


def format_entities_for_enriched_content(entities: dict[str, Any] | None) -> str:
    """Format entity groups for the enriched content string."""
    if not entities:
        return ""

    parts: list[str] = []

    for key, values in entities.items():
        if not isinstance(values, list):
            continue

        joined_values = ", ".join(str(value) for value in values if str(value).strip())
        if joined_values:
            parts.append(f"{key}: {joined_values}")

    return ", ".join(parts)


def build_full_content_enriched(article: dict[str, Any]) -> str:
    """
    Build the enriched content string from full_content, topics, and entities.

    Mirrors the user-provided enrichment format.
    """
    full_content = article.get("full_content", "").strip()
    topics_text = format_topics_for_enriched_content(article.get("topics"))
    entities_text = format_entities_for_enriched_content(article.get("entities"))

    enriched = full_content

    if topics_text:
        enriched += f". Topics: {topics_text}"

    if entities_text:
        enriched += f". Entities: {entities_text}"

    return enriched


def enrich_articles_with_full_content(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach full_content_enriched to every article in a batch."""
    for article in articles:
        article["full_content_enriched"] = ""
        article["enrichment_build_error"] = None

        try:
            enriched_content = build_full_content_enriched(article)
            if not enriched_content.strip():
                article["enrichment_build_error"] = "empty full_content_enriched"
                logger.warning(
                    "Empty enriched content for article %s",
                    article.get("link", "unknown"),
                )
                continue

            article["full_content_enriched"] = enriched_content

        except Exception as exc:
            article["enrichment_build_error"] = str(exc)
            logger.exception(
                "Failed to build full_content_enriched for article %s",
                article.get("link", "unknown"),
            )

    return articles


def _create_embeddings_with_retry(inputs: list[str]) -> list[list[float]]:
    """Call the OpenAI embeddings API with retry/backoff."""
    client = get_openai_client()
    last_error: Exception | None = None

    for attempt in range(1, config.OPENAI_MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                input=inputs,
                model=config.OPENAI_EMBEDDING_MODEL,
            )
            return [item.embedding for item in response.data]

        except RateLimitError as exc:
            last_error = exc
            delay = config.OPENAI_RETRY_BASE_DELAY_SECONDS * attempt
            logger.warning(
                "OpenAI rate limit hit on attempt %d/%d. Retrying in %.1fs.",
                attempt,
                config.OPENAI_MAX_RETRIES,
                delay,
            )
            time.sleep(delay)

        except (APIStatusError, APIError) as exc:
            last_error = exc
            if attempt >= config.OPENAI_MAX_RETRIES:
                break

            delay = config.OPENAI_RETRY_BASE_DELAY_SECONDS * attempt
            logger.warning(
                "OpenAI API error on attempt %d/%d: %s. Retrying in %.1fs.",
                attempt,
                config.OPENAI_MAX_RETRIES,
                exc,
                delay,
            )
            time.sleep(delay)

        except Exception as exc:
            raise EmbeddingError("Unexpected OpenAI embedding failure") from exc

    raise EmbeddingError(
        f"OpenAI embedding request failed after {config.OPENAI_MAX_RETRIES} attempts"
    ) from last_error


def embed_articles_batch(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Generate embedding vectors for a batch of articles.

    Articles with empty full_content_enriched are skipped and tagged with
    embedding_error. A batch-level API failure raises EmbeddingError.
    """
    embeddable_indices: list[int] = []
    embeddable_inputs: list[str] = []

    for index, article in enumerate(articles):
        article["embedding_vector"] = None
        article["embedding_error"] = None

        enriched_content = article.get("full_content_enriched", "").strip()
        if not enriched_content:
            article["embedding_error"] = (
                article.get("enrichment_build_error") or "missing full_content_enriched"
            )
            continue

        embeddable_indices.append(index)
        embeddable_inputs.append(enriched_content)

    if not embeddable_inputs:
        logger.warning("No embeddable articles in batch; skipping OpenAI request.")
        return articles

    logger.info(
        "Requesting OpenAI embeddings for %d/%d articles.",
        len(embeddable_inputs),
        len(articles),
    )

    embeddings = _create_embeddings_with_retry(embeddable_inputs)

    if len(embeddings) != len(embeddable_indices):
        raise EmbeddingError(
            "OpenAI returned a different number of embeddings than requested."
        )

    for index, embedding in zip(embeddable_indices, embeddings):
        articles[index]["embedding_vector"] = embedding

    failed_count = sum(1 for article in articles if article.get("embedding_error"))
    if failed_count:
        logger.warning(
            "%d/%d articles in batch were not embedded.",
            failed_count,
            len(articles),
        )

    return articles


def enrich_and_embed_batch(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build full_content_enriched and embedding_vector for a processed batch."""
    articles = enrich_articles_with_full_content(articles)
    return embed_articles_batch(articles)
