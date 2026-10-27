from __future__ import annotations

import argparse
import logging
from typing import List, Optional

from news_clustering.config import NewsClusteringConfig
from news_clustering.log import configure_logging
from news_clustering.prepare import prepare_clusters

logger = logging.getLogger(__name__)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Daily news clustering job")
    parser.add_argument("--date", help="Job date YYYY-MM-DD (UTC today if omitted)")
    args = parser.parse_args(argv)

    configure_logging()
    config = NewsClusteringConfig.from_env()
    if args.date:
        config = config.model_copy(update={"job_date": args.date})

    try:
        result = prepare_clusters(config)
        manifest = result["manifest"]
        logger.info("Finished with status=%s", manifest["status"])
        return 0 if manifest["status"] in {"success", "partial"} else 1
    except Exception:
        logger.exception("Daily clustering job failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
