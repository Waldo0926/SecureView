from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 -- registers every model with Base.metadata
from app.core.config import settings
from app.core.database import Base
from app.core.migration_defaults import mysql_timestamp_defaults_equivalent

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _compare_server_default(
    migration_context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
):
    if migration_context.dialect.name != "mysql":
        return None

    if mysql_timestamp_defaults_equivalent(inspected_default, rendered_metadata_default):
        return False
    return None


def run_migrations_offline() -> None:
    """Render migrations without opening a database connection."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=_compare_server_default,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a short-lived, non-pooled connection."""
    connectable = create_engine(
        settings.DATABASE_URL,
        poolclass=pool.NullPool,
        connect_args=settings.DATABASE_CONNECT_ARGS,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=_compare_server_default,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
