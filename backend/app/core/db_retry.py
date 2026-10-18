from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# MySQL error codes that mean "the transaction was rolled back for reasons outside its own
# logic; the same work would very likely succeed if simply run again". Both leave InnoDB
# with no transaction left to resume -- the caller starts over from its first statement.
_DEADLOCK = 1213  # "Deadlock found when trying to get lock; try restarting transaction"
_LOCK_WAIT_TIMEOUT = 1205  # "Lock wait timeout exceeded; try restarting transaction"
_RETRYABLE_MYSQL_ERRORS = frozenset({_DEADLOCK, _LOCK_WAIT_TIMEOUT})

T = TypeVar("T")

# Only the MySQL error code and the attempt numbers are logged, never the statement or its
# parameters: those can carry file names, user identifiers or key material.
_LOGGER = logging.getLogger("secureview.db")


def is_retryable_deadlock(exc: BaseException) -> bool:
    """True for a MySQL deadlock or lock-wait timeout surfaced as an `OperationalError`.

    Both are MySQL's own documented signal to retry the whole transaction (see "Deadlocks
    in InnoDB" in the MySQL manual), not a bug to fix in the query. Anything else -- a
    constraint violation, a lost connection, a syntax error -- is a real failure and must
    not be retried.
    """
    if not isinstance(exc, OperationalError):
        return False
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    return bool(args) and args[0] in _RETRYABLE_MYSQL_ERRORS


def run_with_deadlock_retry(
    db: Session,
    operation: Callable[[], T],
    *,
    attempts: int = 3,
) -> T:
    """Run `operation` against `db`, retrying on a MySQL deadlock or lock-wait timeout.

    A deadlock aborts the *entire* transaction, not just the statement that lost -- InnoDB
    has already rolled it back by the time the driver raises. `operation` must therefore be
    safe to run again from its first statement: re-reading rows under a fresh lock rather
    than reusing anything read or locked by the failed attempt. `db.rollback()` is called
    before every retry to put the session back in a clean state, matching what MySQL already
    did to the transaction.

    Only `OperationalError` is inspected here; every other exception `operation` raises
    propagates immediately without a retry or an extra rollback, exactly as if this
    function were not in the call chain.
    """
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError as exc:
            db.rollback()
            if attempt >= attempts or not is_retryable_deadlock(exc):
                raise
            _LOGGER.warning(
                "mysql_transaction_retry code=%s attempt=%d of %d",
                exc.orig.args[0],
                attempt + 1,
                attempts,
            )
    raise AssertionError("unreachable: the loop above always returns or raises")
