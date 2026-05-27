import pytest
from sqlalchemy import text

from immo_ne_collector.db import AsyncSessionLocal, engine

TRUNCATE_SQL = text(
    "TRUNCATE TABLE source_listings, properties, search_mandates, daily_runs RESTART IDENTITY CASCADE"
)


async def _truncate_db_tables() -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await session.execute(TRUNCATE_SQL)
        await session.commit()


@pytest.fixture(autouse=True)
async def isolate_db_for_marked_tests(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("db") is None:
        yield
        return

    await _truncate_db_tables()
    yield
    await _truncate_db_tables()
