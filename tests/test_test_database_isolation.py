import pytest

from immo_ne_collector.db import engine
from tests import conftest as suite_conftest


def test_suite_runs_on_a_dedicated_test_database():
    assert engine.url.database.endswith("_test")


async def test_truncate_refuses_non_test_database(monkeypatch):
    class FakeEngine:
        class url:  # noqa: N801
            database = "immo_ne"

    monkeypatch.setattr(suite_conftest, "engine", FakeEngine)
    with pytest.raises(RuntimeError, match="pas une base de test"):
        await suite_conftest._truncate_db_tables()


def test_explicit_test_url_must_end_with_test(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/immo_ne")
    with pytest.raises(RuntimeError, match="_test"):
        suite_conftest._resolve_test_url()
