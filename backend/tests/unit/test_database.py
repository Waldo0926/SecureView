from collections.abc import Generator
from typing import Any

import pytest

from app.core import database


class FakeSession:
    def __init__(self) -> None:
        self.rolled_back = False
        self.closed = False

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _dependency_with(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
) -> Generator[Any, None, None]:
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    return database.get_db()


def test_database_dependency_closes_successful_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    dependency = _dependency_with(monkeypatch, session)

    assert next(dependency) is session
    dependency.close()

    assert session.closed is True
    assert session.rolled_back is False


def test_database_engine_forwards_connection_security_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected_engine = object()

    def fake_create_engine(database_url: str, **options: Any) -> object:
        captured["url"] = database_url
        captured.update(options)
        return expected_engine

    monkeypatch.setattr(database, "create_engine", fake_create_engine)

    result = database.create_db_engine(
        "mysql+pymysql://example.invalid/database",
        connect_args={"ssl_verify_identity": True},
    )

    assert result is expected_engine
    assert captured["connect_args"] == {"ssl_verify_identity": True}
    assert captured["pool_pre_ping"] is True
    assert captured["pool_recycle"] == 3600


def test_database_dependency_rolls_back_failed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    dependency = _dependency_with(monkeypatch, session)
    next(dependency)

    with pytest.raises(RuntimeError, match="database operation failed"):
        dependency.throw(RuntimeError("database operation failed"))

    assert session.rolled_back is True
    assert session.closed is True
