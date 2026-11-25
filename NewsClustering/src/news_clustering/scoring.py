from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from itertools import combinations
from statistics import mean

import numpy as np
from rapidfuzz.fuzz import ratio
from scipy.spatial.distance import cdist

from news_clustering.config import NewsClusteringConfig

logger = logging.getLogger(__name__)


def cluster_density(embeddings, labels, cluster_id, k=2) -> float:
    vectors = embeddings[labels == cluster_id]
    n = vectors.shape[0]
    if n <= k:
        return 0.0
    distances = cdist(vectors, vectors, metric="euclidean")
    densities = []
    for i in range(n):
        neighbor = float(np.sort(distances[i])[1 : k + 1].sum())
        if neighbor:
            densities.append(k / neighbor)
    return float(np.mean(densities)) if densities else 0.0


def diversity_reliability_score(sources: set[str], reliabilities: dict[str, float], alpha=0.1) -> float:
    matched = [reliabilities[source] for source in sources if source in reliabilities]
    avg = sum(matched) / len(matched) if matched else 0.0
    return (1 - math.exp(-alpha * len(sources))) * avg


def topic_consistency(topic_lists: list[list[str]]) -> float:
    scores = []
    for left, right in combinations([set(topics) for topics in topic_lists], 2):
        union = len(left | right)
        if union:
            scores.append(len(left & right) / union)
    return float(mean(scores)) if scores else 0.0


def majority_topic_consistency(topic_lists: list[list[str]]) -> float:
    if not topic_lists:
        return 0.0
    counter: Counter[str] = Counter()
    for topics in topic_lists:
        counter.update(topics)
    if not counter:
        return 0.0
    dominant, _ = counter.most_common(1)[0]
    return sum(dominant in topics for topics in topic_lists) / len(topic_lists)


def flatten_entities(article_entities: dict) -> list[str]:
    entities = []
    for values in (article_entities or {}).values():
        entities.extend(values)
    return list({str(entity).lower().strip().replace(".", "") for entity in entities})


def fuzzy_jaccard(set_a, set_b, threshold=85):
    if not set_a and not set_b:
        return None
    matched_a, matched_b = set(), set()
    for i, left in enumerate(set_a):
        best_j, best = None, 0
        for j, right in enumerate(set_b):
            score = ratio(left, right)
            if score > best:
                best, best_j = score, j
        if best >= threshold and best_j is not None:
            matched_a.add(i)
            matched_b.add(best_j)
    union = len(set_a) + len(set_b) - len(matched_a)
    return len(matched_a) / union if union else 0.0


def _share_map(labels_per_article: list[list[str]]) -> dict[str, float]:
    """Map each label to the fraction of articles that contain it."""
    n = len(labels_per_article)
    if not n:
        return {}
    counts: Counter[str] = Counter()
    for labels in labels_per_article:
        counts.update({str(label).strip() for label in labels if str(label).strip()})
    ordered = sorted(counts, key=lambda name: (-counts[name], name))
    return {name: round(counts[name] / n, 4) for name in ordered}


def cluster_topic_stats(articles: list[dict]) -> dict[str, float]:
    return _share_map([article.get("topics") or [] for article in articles])


def cluster_entity_stats(articles: list[dict]) -> dict[str, float]:
    return _share_map(
        [flatten_entities(article.get("entities") or {}) for article in articles]
    )


def entity_consistency(articles: list[dict], threshold=85) -> float:
    sets = [flatten_entities(article.get("entities", {})) for article in articles]
    scores = [
        score
        for left, right in combinations(sets, 2)
        if (score := fuzzy_jaccard(left, right, threshold)) is not None
    ]
    return mean(scores) if scores else 0.0


def score_clusters(articles, embeddings, labels, config: NewsClusteringConfig) -> list[dict]:
    reliabilities = config.load_reliabilities()
    grouped = defaultdict(list)
    hdbscan_label = {}
    for article, label in zip(articles, labels):
        label = int(label)
        if label < 0:
            continue
        cluster_id = article.get("cluster_id")
        grouped[cluster_id].append(article)
        hdbscan_label[cluster_id] = label

    clusters = []
    for cluster_id, members in sorted(grouped.items(), key=lambda item: hdbscan_label[item[0]]):
        topics = [article.get("topics") or [] for article in members]
        cluster = {
            "cluster_id": cluster_id,
            "cluster_size": len(members),
            "cluster_density": cluster_density(
                embeddings, labels, hdbscan_label[cluster_id], config.density_k
            ),
            "membership_probability": float(
                np.mean([article.get("cluster_proba") or 0 for article in members])
            ),
            "diversity_reliability": diversity_reliability_score(
                {article.get("source") for article in members},
                reliabilities,
                config.reliability_alpha,
            ),
            "topic_consistency": topic_consistency(topics),
            "majority_topic_consistency": majority_topic_consistency(topics),
            "entity_consistency": entity_consistency(members, config.fuzzy_entity_threshold),
            "cluster_topics": cluster_topic_stats(members),
            "cluster_entities": cluster_entity_stats(members),
            "summary": "",
        }
        cluster["consistency_score"] = (
            cluster["topic_consistency"]
            + cluster["majority_topic_consistency"]
            + cluster["entity_consistency"]
        )
        cluster["big_story_score"] = cluster["diversity_reliability"] * cluster["consistency_score"]
        clusters.append(cluster)
    logger.info("Scored %s clusters", len(clusters))
    return clusters


def rank_clusters(clusters: list[dict], config: NewsClusteringConfig) -> list[dict]:
    return sorted(clusters, key=lambda cluster: cluster["big_story_score"])
