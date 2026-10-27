from editorial.prompts import (
    articles_for_clusters,
    attach_hashed_cluster_ids,
    cluster_id,
    cluster_input,
)
from editorial.s3 import attach_cluster_ids


def test_attach_cluster_ids_maps_hashed_ids_to_integer_cluster_ids():
    articles = [
        {"id": "a1", "title": "One", "full_content": "text one"},
        {"id": 2, "title": "Two", "full_content": "text two"},
        {"id": "noise", "title": "Noise", "full_content": "ignore"},
    ]
    clusters = [
        {"cluster_id": 7, "hashed_cluster_id": "hash-a", "summary": "Story A"},
        {"cluster_id": 8, "hashed_cluster_id": "hash-b", "summary": "Story B"},
    ]
    assignments = [
        {"article_id": "a1", "cluster_id": "hash-a"},
        {"article_id": 2, "cluster_id": "hash-b"},
        {"article_id": "noise", "cluster_id": "hash-noise"},
    ]

    attach_cluster_ids(articles, clusters, assignments)

    assert articles[0]["cluster_id"] == 7
    assert articles[0]["hashed_cluster_id"] == "hash-a"
    assert articles[1]["cluster_id"] == 8
    assert "cluster_id" not in articles[2] or articles[2].get("cluster_id") != 7
    assert articles[2]["hashed_cluster_id"] == "hash-noise"


def test_articles_for_clusters_uses_integer_ids():
    articles = [
        {"cluster_id": 7, "hashed_cluster_id": "hash-a", "full_content": "alpha"},
        {"cluster_id": 8, "hashed_cluster_id": "hash-b", "full_content": "beta"},
        {"hashed_cluster_id": "hash-a", "full_content": "should not match hashed id"},
    ]
    assert articles_for_clusters(articles, [7]) == ["alpha"]
    assert articles_for_clusters(articles, ["7"]) == ["alpha"]
    assert articles_for_clusters(articles, [99]) == []


def test_writer_helpers_use_integer_ids_and_keep_hashed():
    clusters = [
        {"cluster_id": 7, "hashed_cluster_id": "hash-a", "summary": "Story A"},
        {"cluster_id": 8, "hashed_cluster_id": "hash-b", "summary": "Story B"},
    ]
    assert cluster_id(clusters[0]) == 7
    prompt = cluster_input(clusters)
    assert "CLUSTER 7" in prompt
    assert "hash-a" not in prompt

    newsletter = {
        "main_section": {"selected_plan": {"clusters": [7, 8]}},
        "main_section_candidate_plans": [{"clusters": [7]}],
        "headlines": {"headlines": [{"cluster_id": 7, "headline": "A"}]},
        "candidate_headlines": [{"cluster_id": 8, "headline": "B"}],
        "stories_to_watch": {"stories_to_watch": [{"cluster_id": 7, "headline": "C"}]},
        "candidate_stories_to_watch": [{"cluster_id": 8, "headline": "D"}],
    }
    attach_hashed_cluster_ids(newsletter, clusters)
    assert newsletter["main_section"]["selected_plan"]["clusters"] == [7, 8]
    assert newsletter["main_section"]["selected_plan"]["hashed_cluster_ids"] == [
        "hash-a",
        "hash-b",
    ]
    assert newsletter["headlines"]["headlines"][0]["hashed_cluster_id"] == "hash-a"
    assert newsletter["candidate_stories_to_watch"][0]["hashed_cluster_id"] == "hash-b"
