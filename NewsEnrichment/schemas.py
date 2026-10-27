"""GLiNER2 schema definitions for topic classification and entity extraction."""

TOPIC_DISPLAY_NAMES: dict[str, str] = {
    "politics_and_government": "Politics and Government",
    "business_and_economy": "Business and Economy",
    "technology": "Technology",
    "health_and_medicine": "Health and Medicine",
    "science_and_research": "Science and Research",
    "crime_and_legal": "Crime and Legal",
    "entertainment_and_culture": "Entertainment and Culture",
    "environment_climate": "Environment and Climate",
    "sports": "Sports",
}

TOPIC_LABELS: dict[str, str] = {
    "politics_and_government": (
        "Government actions and institutions, including elections, parties, legislation, "
        "regulation, diplomacy, international summits (e.g., G7, UN), public policy debates, "
        "and political decisions affecting society or the economy. Includes political strategy, "
        "political party positions, and government-led initiatives."
    ),
    "business_and_economy": (
        "Companies, corporate performance, financial results, markets, startups, investments, "
        "labor markets, inflation, economic indicators, corporate strategy, mergers, "
        "restructuring, and sector-wide economic trends. Includes business consequences of "
        "political or environmental events."
    ),
    "technology": (
        "Software, hardware, AI systems, cybersecurity, internet platforms, digital "
        "infrastructure, engineering innovation, and applied scientific technologies. "
        "Includes technology companies and product development."
    ),
    "health_and_medicine": (
        "Diseases, public health, healthcare systems, medical treatments, pharmaceuticals, "
        "medical research, epidemiology, and health policy. Includes outbreaks, hospital "
        "systems, and medical professionals."
    ),
    "science_and_research": (
        "Scientific discovery and research in physics, biology, chemistry, space, earth "
        "sciences, and academic studies. Includes climate science, environmental research, "
        "and fundamental scientific findings independent of policy or markets."
    ),
    "crime_and_legal": (
        "Criminal investigations, fraud, policing, courts, lawsuits, regulatory enforcement, "
        "legal disputes, government settlements, legal rulings, official legal orders by "
        "agencies or attorneys general, consent decrees and judicial decisions. Includes "
        "cybercrime and cross-border investigations."
    ),
    "entertainment_and_culture": (
        "Creative industries and cultural content including video games, film, television, "
        "music, publishing, streaming platforms, social media creators, celebrities, and "
        "cultural products. Includes entertainment companies and industry news even when "
        "discussing financial performance or corporate strategy."
    ),
    "environment_climate": (
        "Environmental systems and changes including climate change, global warming, extreme "
        "weather events, natural disasters, ecosystems, pollution, energy transition, and "
        "environmental impacts. Includes climate-related science, policy, economic risks, and "
        "institutional climate discussions."
    ),
    "sports": (
        "Professional and amateur sports, teams, athletes, competitions, leagues, rankings, "
        "transfers, tournaments, and sporting organizations."
    ),
}

ENTITY_LABELS: dict[str, str] = {
    "PERSON": (
        "Individual human beings mentioned in the text, including politicians, executives, "
        "public figures, journalists, scientists, athletes, and celebrities. Extract only "
        "real people who are actively involved in or directly referenced by the news story "
        "(speaking, acting, being affected, or being investigated)."
    ),
    "ORGANIZATION": (
        "Formal groups with institutional identity, including companies, government bodies, "
        "political parties, NGOs, courts, regulatory agencies, international institutions, "
        "military bodies, and unions. Includes both public and private organizations that can "
        "take actions or make decisions."
    ),
    "LOCATION": (
        "Geopolitical or geographic entities where events occur or are relevant, including "
        "countries, cities, regions, states, and supranational blocs (e.g., EU, NATO regions). "
        "Include both physical places and commonly used administrative or political regions."
    ),
    "EVENT": (
        "Any structured occurrence involving change or action over time, including named events "
        "(e.g., elections, tournaments, summits) AND implicit events described in text such "
        "as business restructuring, financial transactions, fundraising rounds, strategic shifts, "
        "bankruptcy proceedings, mergers, investigations, policy announcements, and "
        "organizational transitions. Events do not need to have official names; any clearly "
        "described process or occurrence counts."
    ),
    "LIVING_BEING": (
        "Non-human living organisms mentioned in news, including animals, wildlife, pets, "
        "livestock, marine life, and biological organisms when they are relevant to the story "
        "(e.g. outbreaks, conservation, incidents, research subjects). Includes named animals "
        "(e.g. racehorses, famous pets) and unnamed groups when they are treated as entities "
        "(e.g. herds, species in events)."
    ),
    "PRODUCT": (
        "Specific identifiable artifacts, services, offerings, or creative works that are "
        "created by organizations or individuals and referenced as distinct units in news. "
        "Includes physical goods (e.g., smartphones, vehicles, medical devices), digital "
        "products (e.g., software applications, platforms, AI systems), and media products "
        "or creative works (e.g., films, television series, books, albums, songs, video "
        "games). Products are typically things that can be bought, used, consumed, released, "
        "updated, or discontinued, and are treated as concrete items rather than the "
        "organizations or people behind them."
    ),
    "FINANCIAL_INSTRUMENT": (
        "Tradable financial assets and market-referenced instruments used in economic and "
        "financial contexts. Includes equities (stocks), bonds, indices, ETFs, currencies "
        "when used in exchange-rate contexts, commodities when discussed as traded assets, "
        "derivatives, and cryptocurrencies when treated as financial assets. These entities "
        "represent measurable market values and are typically quoted, traded, or tracked in "
        "financial markets."
    ),
}
