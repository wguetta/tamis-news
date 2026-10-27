import json

from editorial.config import EditorialConfig
from editorial.s3 import (
    existing_reader_emails,
    manifest_object_key,
    newsletter_object_key,
    save_newsletters,
)
from tests.fakes import FakeS3


def test_newsletter_object_key_uses_email_under_date_folder():
    assert (
        newsletter_object_key("2026-09-28", "alex.morgan@example.com")
        == "date=2026-09-28/alex.morgan@example.com.jsonl"
    )


def test_save_newsletters_writes_jsonl_per_reader_and_manifest():
    config = EditorialConfig(
        job_date="2026-09-28",
        newsletters_s3_bucket="readers-newsletters--eun1-az1--x-s3",
    )
    newsletters = [
        {
            "email": "alex.morgan@example.com",
            "topics": ["politics_and_government"],
            "main_section": {"title": "A", "body": "aaa"},
            "headlines": {"headlines": []},
            "stories_to_watch": {"stories_to_watch": []},
            "main_section_candidate_plans": [],
            "candidate_headlines": [],
            "candidate_stories_to_watch": [],
        },
        {
            "email": "sam.chen@example.net",
            "topics": ["health"],
            "main_section": {"title": "B", "body": "bbb"},
            "headlines": {"headlines": []},
            "stories_to_watch": {"stories_to_watch": []},
            "main_section_candidate_plans": [],
            "candidate_headlines": [],
            "candidate_stories_to_watch": [],
        },
    ]
    s3 = FakeS3()

    manifest = save_newsletters(newsletters, config, s3=s3)

    bucket = config.newsletters_s3_bucket
    alex_key = newsletter_object_key("2026-09-28", "alex.morgan@example.com")
    sam_key = newsletter_object_key("2026-09-28", "sam.chen@example.net")
    manifest_key = manifest_object_key("2026-09-28")

    alex_body = s3.objects[(bucket, alex_key)]["Body"].decode("utf-8")
    assert json.loads(alex_body.strip()) == newsletters[0]
    assert s3.objects[(bucket, alex_key)]["ContentType"] == "application/jsonl"

    sam_body = s3.objects[(bucket, sam_key)]["Body"].decode("utf-8")
    assert json.loads(sam_body.strip()) == newsletters[1]

    saved_manifest = json.loads(s3.objects[(bucket, manifest_key)]["Body"].decode("utf-8"))
    assert saved_manifest["date"] == "2026-09-28"
    assert saved_manifest["status"] == "success"
    assert saved_manifest["bucket"] == bucket
    assert saved_manifest["newsletter_count"] == 2
    assert [row["email"] for row in saved_manifest["newsletters"]] == [
        "alex.morgan@example.com",
        "sam.chen@example.net",
    ]
    assert saved_manifest["newsletters"][0]["key"] == alex_key
    assert saved_manifest["date"] == manifest["date"]
    assert {row["email"] for row in saved_manifest["newsletters"]} == {
        row["email"] for row in manifest["newsletters"]
    }


def test_existing_reader_emails_from_jsonl_and_manifest():
    config = EditorialConfig(
        job_date="2026-09-28",
        newsletters_s3_bucket="readers-newsletters--eun1-az1--x-s3",
    )
    s3 = FakeS3()
    bucket = config.newsletters_s3_bucket
    key = newsletter_object_key("2026-09-28", "alex.morgan@example.com")
    s3.put_object(Bucket=bucket, Key=key, Body=b"{}\n", ContentType="application/jsonl")
    s3.put_object(
        Bucket=bucket,
        Key=manifest_object_key("2026-09-28"),
        Body=json.dumps(
            {
                "date": "2026-09-28",
                "newsletters": [{"email": "sam.chen@example.net", "key": "x"}],
            }
        ).encode("utf-8"),
        ContentType="application/json",
    )

    assert existing_reader_emails(s3, bucket, "2026-09-28") == {
        "alex.morgan@example.com",
        "sam.chen@example.net",
    }
    assert existing_reader_emails(s3, bucket, "2026-09-27") == set()
