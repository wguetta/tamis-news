from __future__ import annotations

import logging

import numpy as np
import umap
from sklearn.cluster import HDBSCAN

from news_clustering.config import NewsClusteringConfig

logger = logging.getLogger(__name__)


class UmapInputError(Exception):
    """Not enough valid embeddings to run UMAP safely."""


def check_umap_inputs(articles: list[dict], config: NewsClusteringConfig) -> None:
    n = len(articles)
    min_articles = max(config.umap_n_neighbors + 1, config.umap_n_components + 1)
    if n < min_articles:
        raise UmapInputError(
            f"Thin day for UMAP: need at least {min_articles} articles "
            f"(n_neighbors={config.umap_n_neighbors}, n_components={config.umap_n_components}), got {n}"
        )
    dimensions = set()
    for index, article in enumerate(articles):
        vector = article.get("embedding_vector")
        if not vector:
            raise UmapInputError(f"Article {index} is missing embedding_vector")
        try:
            dimensions.add(len(vector))
        except TypeError as exc:
            raise UmapInputError(f"Article {index} has a non-sequence embedding_vector") from exc
    if len(dimensions) != 1:
        raise UmapInputError(f"Inconsistent embedding dimensions: {sorted(dimensions)}")
    dim = next(iter(dimensions))
    if dim < config.umap_n_components:
        raise UmapInputError(
            f"embedding_vector size {dim} is smaller than umap_n_components={config.umap_n_components}"
        )
    logger.info("UMAP input check passed: %s articles, embedding dim %s", n, dim)


def format_cluster_id(job_date: str, hdbscan_id: int) -> str:
    """Public cluster id: 20261112-282, or 20261112-noise for HDBSCAN noise."""
    stamp = job_date.replace("-", "")
    if hdbscan_id == -1:
        return f"{stamp}-noise"
    return f"{stamp}-{hdbscan_id}"


def is_noise_cluster_id(cluster_id) -> bool:
    if cluster_id == -1:
        return True
    return isinstance(cluster_id, str) and cluster_id.endswith("-noise")


def cluster_articles(articles: list[dict], config: NewsClusteringConfig):
    check_umap_inputs(articles, config)
    vectors = np.array([article["embedding_vector"] for article in articles], dtype=float)
    logger.info(
        "Fitting UMAP n_components=%s n_neighbors=%s on %s vectors",
        config.umap_n_components,
        config.umap_n_neighbors,
        len(articles),
    )
    reduced = umap.UMAP(
        n_components=config.umap_n_components,
        n_neighbors=config.umap_n_neighbors,
        random_state=config.umap_random_state,
        min_dist=0.0,
        metric="cosine",
        verbose=False,
    ).fit_transform(vectors)
    clusterer = HDBSCAN(
        min_cluster_size=config.hdbscan_min_cluster_size,
        max_cluster_size=config.hdbscan_max_cluster_size,
        metric="euclidean",
        min_samples=config.hdbscan_min_samples,
        copy=True,
    )
    clusterer.fit(reduced)
    job_date = config.resolve_job_date()
    for article, label, proba in zip(articles, clusterer.labels_, clusterer.probabilities_):
        article["cluster_id"] = format_cluster_id(job_date, int(label))
        article["cluster_proba"] = float(proba)
    cluster_count = int(clusterer.labels_.max()) + 1 if clusterer.labels_.size else 0
    noise = float((clusterer.labels_ == -1).mean()) if clusterer.labels_.size else 0.0
    logger.info("Clusters: %s, noise: %.3f", cluster_count, noise)
    return reduced, clusterer.labels_
