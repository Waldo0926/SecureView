from __future__ import annotations

import logging

import pytest
from sqlalchemy.exc import OperationalError

from app.core.db_retry import is_retryable_deadlock, run_with_deadlock_retry


def _mysql_error(code: int, message: str = "boom") -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(code, message))


class FakeSession:
    def __init__(self) -> None:
        self.rollbacks = 0

    def rollback(self) -> None:
        self.rollbacks += 1


def test_is_retryable_deadlock_accepts_1213_and_1205() -> None:
    assert is_retryable_deadlock(_mysql_error(1213))
    assert is_retryable_deadlock(_mysql_error(1205))


def test_is_retryable_deadlock_rejects_other_operational_errors() -> None:
    assert not is_retryable_deadlock(_mysql_error(1046, "No database selected"))


def test_is_retryable_deadlock_rejects_non_operational_exceptions() -> None:
    assert not is_retryable_deadlock(ValueError("not a deadlock"))


def test_run_with_deadlock_retry_retries_until_success() -> None:
    db = FakeSession()
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise _mysql_error(1213)
        return "ok"

    result = run_with_deadlock_retry(db, operation, attempts=3)

    assert result == "ok"
    assert calls["count"] == 3
    # Every failed attempt rolls back before the next try.
    assert db.rollbacks == 2


def test_run_with_deadlock_retry_gives_up_after_the_attempt_budget() -> None:
    db = FakeSession()
    calls = {"count": 0}

    def operation() -> None:
        calls["count"] += 1
        raise _mysql_error(1213)

    with pytest.raises(OperationalError):
        run_with_deadlock_retry(db, operation, attempts=3)

    assert calls["count"] == 3
    assert db.rollbacks == 3


def test_run_with_deadlock_retry_never_retries_a_non_deadlock_operational_error() -> None:
    db = FakeSession()
    calls = {"count": 0}

    def operation() -> None:
        calls["count"] += 1
        raise _mysql_error(1046, "No database selected")

    with pytest.raises(OperationalError):
        run_with_deadlock_retry(db, operation, attempts=3)

    assert calls["count"] == 1
    assert db.rollbacks == 1


def test_run_with_deadlock_retry_never_touches_other_exceptions() -> None:
    db = FakeSession()
    calls = {"count": 0}

    def operation() -> None:
        calls["count"] += 1
        raise ValueError("unrelated failure")

    with pytest.raises(ValueError):
        run_with_deadlock_retry(db, operation, attempts=3)

    assert calls["count"] == 1
    # Not this function's job to roll back a non-deadlock failure -- the caller's own
    # except clause (as every service here already has) is still responsible for that.
    assert db.rollbacks == 0


def test_each_retry_logs_a_warning_without_the_statement(caplog: pytest.LogCaptureFixture) -> None:
    db = FakeSession()
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise OperationalError(
                "UPDATE files SET secret = 'x'", {"p": "secret"}, Exception(1213, "Deadlock")
            )
        return "ok"

    with caplog.at_level(logging.WARNING, logger="secureview.db"):
        assert run_with_deadlock_retry(db, operation) == "ok"

    messages = [r.getMessage() for r in caplog.records if r.name == "secureview.db"]
    assert messages == [
        "mysql_transaction_retry code=1213 attempt=2 of 3",
        "mysql_transaction_retry code=1213 attempt=3 of 3",
    ]
    assert all("secret" not in m and "UPDATE" not in m for m in messages)


def test_no_warning_when_the_error_is_not_retried(caplog: pytest.LogCaptureFixture) -> None:
    def operation() -> str:
        raise _mysql_error(1046, "No database selected")

    with caplog.at_level(logging.WARNING, logger="secureview.db"), pytest.raises(OperationalError):
        run_with_deadlock_retry(FakeSession(), operation)
    assert not [r for r in caplog.records if r.name == "secureview.db"]
