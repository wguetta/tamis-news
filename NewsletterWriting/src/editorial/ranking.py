from __future__ import annotations

from collections import defaultdict


def topic_jaccard(left: list[str], right: list[str]) -> float:
    a = set(left)
    b = set(right)
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _cluster_key(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def articles_by_cluster_id(articles: list[dict]) -> dict:
    grouped = defaultdict(list)
    for article in articles:
        cluster_id = article.get("cluster_id")
        if cluster_id is None:
            continue
        grouped[_cluster_key(cluster_id)].append(article)
    return grouped


def mean_article_topic_jaccard(reader_topics: list[str], articles: list[dict]) -> float:
    if not articles:
        return 0.0
    scores = [
        topic_jaccard(reader_topics, article.get("topics") or [])
        for article in articles
    ]
    return sum(scores) / len(scores)


def cluster_topic_percentages(articles: list[dict]) -> list[dict]:
    n = len(articles)
    counts: dict[str, int] = defaultdict(int)
    for article in articles:
        for topic in set(article.get("topics") or []):
            counts[topic] += 1
    return [
        {
            "topic": topic,
            "percentage": (counts[topic] / n) if n else 0.0,
        }
        for topic in sorted(counts, key=lambda name: (-counts[name], name))
    ]


def attach_cluster_topics(articles: list[dict], clusters: list[dict]) -> None:
    grouped = articles_by_cluster_id(articles)
    for cluster in clusters:
        members = grouped.get(_cluster_key(cluster["cluster_id"]), [])
        cluster["topics"] = cluster_topic_percentages(members)


def top_clusters_by_story_score(clusters: list[dict], n: int) -> list[dict]:
    return sorted(clusters, key=lambda cluster: cluster.get("big_story_score") or 0)[-n:]


def top_clusters_for_reader(
    clusters: list[dict],
    reader_topics: list[str],
    n: int,
    articles: list[dict],
) -> list[dict]:
    grouped = articles_by_cluster_id(articles)
    scored = []
    for cluster in clusters:
        item = dict(cluster)
        item["topic_matching"] = mean_article_topic_jaccard(
            reader_topics,
            grouped.get(_cluster_key(cluster["cluster_id"]), []),
        )
        scored.append(item)
    return sorted(scored, key=lambda cluster: cluster["topic_matching"])[-n:]
