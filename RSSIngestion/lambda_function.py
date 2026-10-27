from __future__ import annotations
import json
from typing import Any
import logging


from helpers import *
import boto3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ["TAMIS_AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["TAMIS_AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ["AWS_REGION"],
)

raw_rss_bucket = os.environ["RAW_RSS_BUCKET"]
rss_new_unique_articles_bucket = os.environ["RSS_NEW_UNIQUE_ARTICLES_BUCKET"]


def lambda_handler(event, context):
    
    #feeds_path = get_feeds_path_from_env()
    feeds_path = "feeds.json"
    rss_articles, errors = extract_all_stories(feeds_path)
    status_code = 200 if rss_articles or not errors else 502

    previous_rss_articles = load_latest_file(s3_client=s3, bucket=raw_rss_bucket)
    new_articles = get_new_articles(rss_articles, previous_rss_articles)
    unique_new_articles = remove_duplicates(new_articles)

    unique_new_articles = generate_unique_ids(unique_new_articles)

    dt = datetime.now(timezone.utc)
    rss_articles_key = save_data_to_s3(s3_client=s3, articles=rss_articles, bucket=raw_rss_bucket, dt=dt)
    unique_new_articles_key = save_data_to_s3(s3_client=s3, articles=unique_new_articles, bucket=rss_new_unique_articles_bucket, dt=dt)
    print(rss_articles_key)
    print(unique_new_articles_key)


    return {
        'statusCode': 200
        #'body': json.dumps('Success!')
    }
