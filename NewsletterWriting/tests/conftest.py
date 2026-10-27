import pytest

from editorial.config import EditorialConfig


@pytest.fixture
def config() -> EditorialConfig:
    return EditorialConfig(job_date="2026-09-13")
