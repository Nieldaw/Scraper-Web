"""Configuration pytest : les tests tournent sur une base *dédiée* (`<base>_test`).

La base de développement n'est jamais touchée : `DATABASE_URL` est redirigée vers la base de test
AVANT l'import de `immo_ne_collector.db`, la base de test est créée si besoin et son schéma est
recréé à chaque session. En plus, le TRUNCATE refuse de s'exécuter si la base ne se termine pas
par `_test`.

Base de test : variable `TEST_DATABASE_URL` si définie, sinon le nom de la base de
`DATABASE_URL` + `_test` (ex. `immo_ne` -> `immo_ne_test`).
"""

import asyncio
import os

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from immo_ne_collector.config import get_settings

TEST_SUFFIX = "_test"


def _resolve_test_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    base = make_url(explicit or os.environ.get("DATABASE_URL") or get_settings().database_url)
    name = base.database or "immo_ne"
    if not name.endswith(TEST_SUFFIX):
        if explicit:
            raise RuntimeError(
                f"TEST_DATABASE_URL doit viser une base dont le nom se termine par '{TEST_SUFFIX}' "
                f"(reçu : '{name}')."
            )
        name += TEST_SUFFIX
    return base.set(database=name).render_as_string(hide_password=False)


TEST_DATABASE_URL = _resolve_test_url()
# Doit précéder tout import de immo_ne_collector.db (qui crée l'engine à l'import).
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
get_settings.cache_clear()

from immo_ne_collector.db import AsyncSessionLocal, Base, engine  # noqa: E402
from immo_ne_collector import models  # noqa: E402,F401  (enregistre les tables sur Base)

TRUNCATE_SQL = text(
    "TRUNCATE TABLE source_listings, properties, search_mandates, daily_runs RESTART IDENTITY CASCADE"
)


async def _prepare_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
    )
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await admin.close()

    schema_engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with schema_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await schema_engine.dispose()


def pytest_sessionstart(session: pytest.Session) -> None:
    try:
        asyncio.run(_prepare_test_database())
    except (OSError, asyncpg.PostgresError) as exc:
        # Sans PostgreSQL, les tests non marqués `db` restent exécutables.
        print(f"\n[conftest] base de test indisponible ({exc}); tests `db` en erreur attendue.")


async def _truncate_db_tables() -> None:
    database = engine.url.database or ""
    if not database.endswith(TEST_SUFFIX):  # garde-fou ultime : jamais sur la base de dev
        raise RuntimeError(f"Refus de vider la base '{database}' : ce n'est pas une base de test.")
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
