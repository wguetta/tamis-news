# tamis-news

Pipeline that turns RSS feeds into clustered stories and a newsletter for each reader. The four stages run separately and pass data through Amazon S3. Step Functions starts them. That state machine is not in this repository.

Python 3.11 or newer.

## Stages

1. **RSSIngestion** is an AWS Lambda. It reads `feeds.json`, keeps stories from the last 24 hours, drops articles already stored, and writes the raw dump plus the new unique articles to S3.
2. **NewsEnrichment** runs on EC2. It loads the unique articles, extracts full text, adds topics and entities, computes embeddings, and writes the enriched articles to S3. A failed run can resume from its checkpoints.
3. **NewsClustering** runs on EC2. It reduces embeddings with UMAP, groups stories with HDBSCAN, scores clusters using `reliability.json`, and summarizes them.
4. **NewsletterWriting** runs on EC2. It ranks clusters for each reader in `readers.json`, drafts the newsletter, stores it in S3, and sends it.

## EC2 setup

On each instance, from that stage's directory:

```bash
bash setup_env.sh
```

`setup_env.sh` creates the virtualenv named in `run.sh` and installs `requirements.txt`. Create a `.env` in the same directory before the first run. `run.sh` loads it and then starts `main.py`. `init_dotenv.sh` can write that file. It is gitignored because it holds live keys. Do not commit it.

| Stage | Virtualenv |
| --- | --- |
| NewsEnrichment | `/home/ec2-user/NewsEnrichmentEnv` |
| NewsClustering | `/home/ec2-user/NewsClustering/.venv` |
| NewsletterWriting | `/home/ec2-user/NewsletterWriting/.venv` |

Newsletter tests:

```bash
cd NewsletterWriting
python -m pytest
```

## Environment variables

**Lambda**

| Variable | Purpose |
| --- | --- |
| `TAMIS_AWS_ACCESS_KEY_ID` | AWS access key |
| `TAMIS_AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | Region, set by Lambda |
| `RAW_RSS_BUCKET` | Raw RSS dump |
| `RSS_NEW_UNIQUE_ARTICLES_BUCKET` | New unique articles |

`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are reserved on Lambda, so the keys use the `TAMIS_` names.

**Enrichment**

| Variable | Purpose |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | AWS region |
| `OPENAI_API_KEY` | Embeddings |
| `UNIQUE_ARTICLES_BUCKET` | Input from ingestion |
| `ENRICHED_ARTICLES_BUCKET` | Enriched articles |

`LOAD_HOURS`, `MAX_WORKERS`, and `BATCH_SIZE` are optional. `run.sh` sets them for that instance.

**Clustering**

| Variable | Purpose |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | AWS region |
| `OPENAI_API_KEY` | Cluster summaries |
| `ENRICHED_ARTICLES_BUCKET` | Input from enrichment |
| `CLUSTERS_BUCKET` | Cluster output |
| `ARTICLE_CLUSTER_IDS_BUCKET` | Article-to-cluster ids |

**Newsletter writing**

Clustering's variables, plus:

| Variable | Purpose |
| --- | --- |
| `NEWSLETTERS_BUCKET` | Saved newsletters |
| `SMTP_HOST` | SMTP server |
| `SMTP_PORT` | SMTP port |
| `SMTP_USERNAME` | SMTP user |
| `SMTP_PASSWORD` | SMTP password |
| `FROM_EMAIL` | From address |

`readers.json` in this repository uses placeholder addresses. On the newsletter instance, point `EDITORIAL_READERS_PATH` at the real file, or replace `readers.json` locally and do not commit it.
