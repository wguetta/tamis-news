from __future__ import annotations

import logging
import sys

PACKAGE_LOGGER = "news_clustering"


def configure_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger(PACKAGE_LOGGER)
    if logger.handlers:
        logger.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
