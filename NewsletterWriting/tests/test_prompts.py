from editorial.config import EditorialConfig
from editorial.prompts import load_prompts, render
from editorial.ranking import (
    attach_cluster_topics,
    top_clusters_by_story_score,
    top_clusters_for_reader,
    topic_jaccard,
)


def test_prompts_use_reader_topics():
    config = EditorialConfig(
        n_headlines=2,
        n_stories_to_watch=4,
        headline_details_words=40,
        story_details_words=35,
        main_section_min_words=120,
        main_section_max_words=180,
        n_section_plans=3,
        n_headlines_plan_min=2,
        n_headlines_plan_max=4,
        n_stories_plan_min=2,
        n_stories_plan_max=5,
    )
    values = config.prompt_values(["climate", "energy"])
    main = render(load_prompts("main_section")["plan"]["system"], values)
    headlines = render(load_prompts("headlines")["select"]["system"], values)
    stories = render(load_prompts("stories_to_watch")["select"]["system"], values)
    write = render(load_prompts("main_section")["write"]["system"], values)

    assert "climate and energy" in main
    assert "EXACTLY 3 newsletter sections" in main
    assert "Select exactly 2 headlines" in headlines
    assert "Select exactly 4 stories" in stories
    assert "120–180 words" in write
    assert "politics, economy, business, and technology" not in main


def test_load_readers():
    readers = EditorialConfig(readers_path="readers.json").load_readers()
    assert len(readers) == 2
    assert "email" in readers[0] and "topics" in readers[0]


def test_topic_jaccard():
    assert topic_jaccard(["politics", "tech"], ["politics", "sports"]) == 1 / 3
    assert topic_jaccard(["a"], ["a"]) == 1.0
    assert topic_jaccard(["a"], ["b"]) == 0.0


def test_attach_cluster_topics_and_reader_top_n():
    articles = [
        {"cluster_id": 1, "topics": ["politics_and_government", "technology"]},
        {"cluster_id": 1, "topics": ["politics_and_government"]},
        {"cluster_id": 2, "topics": ["health"]},
        {"cluster_id": 3, "topics": ["entertainment"]},
    ]
    clusters = [
        {"cluster_id": 1, "big_story_score": 1},
        {"cluster_id": 2, "big_story_score": 9},
        {"cluster_id": 3, "big_story_score": 8},
    ]
    attach_cluster_topics(articles, clusters)
    assert clusters[0]["topics"] == [
        {"topic": "politics_and_government", "percentage": 1.0},
        {"topic": "technology", "percentage": 0.5},
    ]
    assert clusters[1]["topics"] == [{"topic": "health", "percentage": 1.0}]

    top_story = top_clusters_by_story_score(clusters, n=2)
    assert [cluster["cluster_id"] for cluster in top_story] == [3, 2]

    reader = top_clusters_for_reader(
        clusters,
        ["politics_and_government", "technology"],
        n=1,
        articles=articles,
    )
    assert reader[0]["cluster_id"] == 1
    assert reader[0]["topic_matching"] == 0.75
