from __future__ import annotations

import os
import re
from collections.abc import Generator

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings

AUTH_TEST_DATABASE_URL_ENV = "AUTH_TEST_DATABASE_URL"


def _is_explicit_test_database(database_name: str) -> bool:
    return re.search(r"(?:^|_)test(?:$|_)", database_name.casefold()) is not None


@pytest.fixture(scope="session")
def auth_mysql_url() -> URL:
    raw_url = os.getenv(AUTH_TEST_DATABASE_URL_ENV)
    if not raw_url:
        pytest.skip(
            f"Set {AUTH_TEST_DATABASE_URL_ENV} to run disposable MySQL auth integration tests"
        )

    database_url = make_url(raw_url)
    if not database_url.drivername.startswith("mysql"):
        pytest.fail(f"{AUTH_TEST_DATABASE_URL_ENV} must use a MySQL driver")
    if not database_url.database or not _is_explicit_test_database(database_url.database):
        pytest.fail(
            f"{AUTH_TEST_DATABASE_URL_ENV} database name must contain a distinct '_test' segment"
        )
    return database_url


@pytest.fixture(scope="session")
def auth_mysql_engine(auth_mysql_url: URL) -> Generator[Engine, None, None]:
    engine = create_engine(auth_mysql_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def auth_mysql_session(auth_mysql_engine: Engine) -> Generator[Session, None, None]:
    connection = auth_mysql_engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        if outer_transaction.is_active:
            outer_transaction.rollback()
        connection.close()


@pytest.fixture
def temporary_auth_mysql_connection() -> Generator[Connection, None, None]:
    """Use connection-local tables only; never mutate permanent application tables."""
    configured_url = os.getenv(AUTH_TEST_DATABASE_URL_ENV)
    database_url = make_url(configured_url) if configured_url else settings.DATABASE_URL
    engine = create_engine(database_url, poolclass=NullPool, pool_pre_ping=True)
    connection: Connection | None = None
    try:
        try:
            connection = engine.connect()
            connection.exec_driver_sql(
                "CREATE TEMPORARY TABLE auth_test_privilege_probe (id INTEGER NOT NULL)"
            )
        except SQLAlchemyError as exc:
            pytest.skip(
                "MySQL is unavailable or CREATE TEMPORARY TABLE is not permitted "
                f"({type(exc).__name__})"
            )
        yield connection
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()
