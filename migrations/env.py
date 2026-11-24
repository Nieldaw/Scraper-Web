from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from immo_ne_collector.config import get_settings
from immo_ne_collector.db import Base
from immo_ne_collector import models  # noqa: F401

config = context.config


def _sync_database_url(url: str) -> str:
    """URL synchrone pour Alembic : pilote psycopg (v3) explicite, quelle que soit la version de SQLAlchemy."""
    for prefix in ("postgresql+asyncpg://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


config.set_main_option("sqlalchemy.url", _sync_database_url(get_settings().database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
