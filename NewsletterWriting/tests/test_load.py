from editorial.prompts import (
    articles_for_clusters,
    cluster_id,
    cluster_input,
)
from editorial.s3 import attach_cluster_ids


def test_attach_cluster_ids_copies_dated_ids_onto_articles():
    articles = [
        {"id": "a1", "title": "One", "full_content": "text one"},
        {"id": 2, "title": "Two", "full_content": "text two"},
        {"id": "noise", "title": "Noise", "full_content": "ignore"},
    ]
    clusters = [
        {"cluster_id": "20261112-7", "summary": "Story A"},
        {"cluster_id": "20261112-8", "summary": "Story B"},
    ]
    assignments = [
        {"article_id": "a1", "cluster_id": "20261112-7"},
        {"article_id": 2, "cluster_id": "20261112-8"},
        {"article_id": "noise", "cluster_id": "20261112-noise"},
    ]

    attach_cluster_ids(articles, clusters, assignments)

    assert articles[0]["cluster_id"] == "20261112-7"
    assert articles[1]["cluster_id"] == "20261112-8"
    assert articles[2]["cluster_id"] == "20261112-noise"


def test_articles_for_clusters_uses_cluster_ids():
    articles = [
        {"cluster_id": "20261112-7", "full_content": "alpha"},
        {"cluster_id": "20261112-8", "full_content": "beta"},
        {"full_content": "should not match without a cluster id"},
    ]
    assert articles_for_clusters(articles, ["20261112-7"]) == ["alpha"]
    assert articles_for_clusters(articles, ["20261112-99"]) == []


def test_writer_helpers_keep_dated_cluster_ids():
    clusters = [
        {"cluster_id": "20261112-7", "summary": "Story A"},
        {"cluster_id": "20261112-8", "summary": "Story B"},
    ]
    assert cluster_id(clusters[0]) == "20261112-7"
    prompt = cluster_input(clusters)
    assert "CLUSTER 20261112-7" in prompt
    assert "CLUSTER 20261112-8" in prompt
