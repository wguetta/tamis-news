from editorial.config import EditorialConfig
from editorial.job import run_newsletters
from editorial.s3 import newsletter_object_key
from tests.fakes import FakeS3


def _config(tmp_path, emails_and_topics):
    readers_path = tmp_path / "readers.json"
    import json

    readers_path.write_text(json.dumps(emails_and_topics), encoding="utf-8")
    return EditorialConfig(
        job_date="2026-09-28",
        newsletters_s3_bucket="readers-newsletters--eun1-az1--x-s3",
        readers_path=str(readers_path),
    )


def _newsletter(email, topics):
    return {
        "email": email,
        "topics": topics,
        "main_section": {"title": email, "body": "x"},
        "headlines": {"headlines": []},
        "stories_to_watch": {"stories_to_watch": []},
        "main_section_candidate_plans": [],
        "candidate_headlines": [],
        "candidate_stories_to_watch": [],
    }


def test_run_skips_existing_and_writes_the_rest(tmp_path, monkeypatch):
    readers = [
        {"email": "alex.morgan@example.com", "topics": ["politics_and_government"]},
        {"email": "sam.chen@example.net", "topics": ["health"]},
    ]
    config = _config(tmp_path, readers)
    s3 = FakeS3()
    bucket = config.newsletters_s3_bucket
    existing_key = newsletter_object_key("2026-09-28", "alex.morgan@example.com")
    s3.put_object(Bucket=bucket, Key=existing_key, Body=b"{}\n", ContentType="application/jsonl")

    loaded = {"called": 0}
    written = []

    def fake_load(config, s3=None):
        loaded["called"] += 1
        return {
            "job_date": "2026-09-28",
            "articles": [],
            "clusters": [{"cluster_id": 1, "big_story_score": 1, "topics": []}],
        }

    def fake_write(llm, reader, clusters, articles, config):
        written.append(reader["email"])
        return _newsletter(reader["email"], reader["topics"])

    sent = []

    def fake_send(newsletter, subject="Your Daily Briefing"):
        sent.append(newsletter["email"])

    monkeypatch.setattr("editorial.job.load_persisted", fake_load)
    monkeypatch.setattr("editorial.job.write_for_reader", fake_write)
    monkeypatch.setattr("editorial.job.send_reader_newsletter", fake_send)
    monkeypatch.setattr("editorial.job.LlmClient", lambda config: object())

    result = run_newsletters(config, s3=s3)

    assert loaded["called"] == 1
    assert written == ["sam.chen@example.net"]
    assert sent == ["sam.chen@example.net"]
    assert result["skipped"] == ["alex.morgan@example.com"]
    assert result["wrote"] == ["sam.chen@example.net"]
    assert result["manifest"]["status"] == "success"
    sam_key = newsletter_object_key("2026-09-28", "sam.chen@example.net")
    assert (bucket, sam_key) in s3.objects


def test_run_skips_load_when_all_readers_already_written(tmp_path, monkeypatch):
    readers = [{"email": "alex.morgan@example.com", "topics": ["politics_and_government"]}]
    config = _config(tmp_path, readers)
    s3 = FakeS3()
    key = newsletter_object_key("2026-09-28", "alex.morgan@example.com")
    s3.put_object(
        Bucket=config.newsletters_s3_bucket,
        Key=key,
        Body=b"{}\n",
        ContentType="application/jsonl",
    )

    def fail_load(*args, **kwargs):
        raise AssertionError("should not load persisted data")

    def fail_write(*args, **kwargs):
        raise AssertionError("should not write a newsletter")

    def fail_send(*args, **kwargs):
        raise AssertionError("should not send a newsletter")

    monkeypatch.setattr("editorial.job.load_persisted", fail_load)
    monkeypatch.setattr("editorial.job.write_for_reader", fail_write)
    monkeypatch.setattr("editorial.job.send_reader_newsletter", fail_send)

    result = run_newsletters(config, s3=s3)
    assert result["wrote"] == []
    assert result["skipped"] == ["alex.morgan@example.com"]
    assert result["manifest"]["status"] == "success"
