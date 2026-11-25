from __future__ import annotations

from editorial.config import EditorialConfig
from editorial.headlines import generate_headlines
from editorial.llm import LlmClient
from editorial.main_section import write_main_section
from editorial.ranking import top_clusters_for_reader
from editorial.s3 import save_newsletters
from editorial.stories import generate_stories_to_watch


def write_for_reader(
    llm: LlmClient,
    reader: dict,
    clusters: list[dict],
    articles: list[dict],
    config: EditorialConfig,
) -> dict:
    reader_clusters = top_clusters_for_reader(
        clusters, reader["topics"], config.top_n_by_reader, articles
    )
    print(f"Writing newsletter for {reader['email']} ({len(reader_clusters)} clusters)")
    main_section = write_main_section(
        llm, reader_clusters, articles, config, reader["topics"]
    )
    headlines = generate_headlines(
        llm, reader_clusters, articles, config, reader["topics"]
    )
    stories_to_watch = generate_stories_to_watch(
        llm, reader_clusters, articles, config, reader["topics"]
    )
    main_section_candidate_plans = main_section.pop("candidate_plans")
    candidate_headlines = headlines.pop("candidate_headlines")
    candidate_stories_to_watch = stories_to_watch.pop("candidate_stories_to_watch")
    newsletter = {
        "email": reader["email"],
        "topics": reader["topics"],
        "main_section": main_section,
        "headlines": headlines,
        "stories_to_watch": stories_to_watch,
        "main_section_candidate_plans": main_section_candidate_plans,
        "candidate_headlines": candidate_headlines,
        "candidate_stories_to_watch": candidate_stories_to_watch,
    }
    return newsletter


def write_for_readers(
    llm: LlmClient,
    readers: list[dict],
    clusters: list[dict],
    articles: list[dict],
    config: EditorialConfig,
    persist: bool = True,
    s3=None,
) -> list[dict]:
    newsletters = [
        write_for_reader(llm, reader, clusters, articles, config)
        for reader in readers
    ]
    if persist:
        save_newsletters(newsletters, config, s3=s3)
    return newsletters
