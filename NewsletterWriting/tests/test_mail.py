from editorial.mail import email_payload


def test_email_payload_maps_written_sections():
    newsletter = {
        "email": "alex.morgan@example.com",
        "main_section": {"title": "Main", "body": "Body"},
        "headlines": {
            "headlines": [
                {"headline": "H1", "details": "d1"},
                {"headline": "H2", "details": "d2"},
                {"headline": "H3", "details": "d3"},
            ]
        },
        "stories_to_watch": {
            "stories_to_watch": [
                {"headline": "S1", "watch_for": "w1", "details": "ignore"},
                {"headline": "S2", "watch_for": "w2", "details": "ignore"},
                {"headline": "S3", "watch_for": "w3", "details": "ignore"},
            ]
        },
    }

    payload = email_payload(newsletter)

    assert payload["main"] == {"title": "Main", "body": "Body"}
    assert payload["headlines"] == [
        {"title": "H1", "details": "d1"},
        {"title": "H2", "details": "d2"},
        {"title": "H3", "details": "d3"},
    ]
    assert payload["stories_to_watch"][0] == {"title": "S1", "details": "w1"}
