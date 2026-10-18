"""The dashboard numbers against real MySQL, driven by real services.

The `_test` database is permanent and shared, so nothing here asserts an absolute count.
Each test takes a snapshot, performs real activity through the same services the API calls,
takes another, and asserts the *difference*. Running every statement is also what proves the
aggregate SQL (conditional sums, `COUNT(DISTINCT)`, the left join) is valid on MySQL 8.4,
which the compiled-SQL unit tests cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine
from tests.integration._concurrency_support import (
    RegisteredUser,
    active_recovery_key,
    file_service,
    register_real_user,
    request_context,
    session_scope,
    upload_file,
)

from app.domain.enums import SystemRole
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin_schema import AdminStatsOut
from app.services.admin_service import AdminService

pytestmark = pytest.mark.integration

FIXTURE_BYTES = len(b"synthetic fixture bytes, not a real document")


def _stats(engine: Engine, admin: RegisteredUser) -> AdminStatsOut:
    with session_scope(engine) as session:
        return AdminService(db=session).platform_stats(actor=admin.actor())


def test_stats_follow_real_registration_upload_integrity_failure_and_disable(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    admin = register_real_user(auth_mysql_engine, prefix="stats-admin", role=SystemRole.ADMIN)
    before = _stats(auth_mysql_engine, admin)

    owner = register_real_user(auth_mysql_engine, prefix="stats-owner")
    with active_recovery_key(auth_mysql_engine) as recovery:
        uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)

    def check_integrity() -> None:
        with session_scope(auth_mysql_engine) as session:
            file_service(session, tmp_path).integrity_check(
                actor=owner.actor(), file_id=uploaded.file_id, context=request_context()
            )

    check_integrity()  # the object is intact: a VALID check

    with session_scope(auth_mysql_engine) as session:
        AdminService(db=session).set_user_enabled(
            actor=admin.actor(),
            user_id=owner.user_uuid,
            enabled=False,
            context=request_context(),
        )

    stored = list((tmp_path / "objects").rglob("*.ciphertext"))
    assert len(stored) == 1
    stored[0].write_bytes(b"damaged on purpose" + stored[0].read_bytes()[18:])
    check_integrity()  # now MODIFIED: a failed check, a CORRUPTED file, a FAIL audit event

    after = _stats(auth_mysql_engine, admin)

    # Accounts: one registered, then disabled, so it is counted once and not as active.
    assert after.users.total == before.users.total + 1
    assert after.users.disabled == before.users.disabled + 1
    assert after.users.active == before.users.active
    assert after.users.created_last_7_days == before.users.created_last_7_days + 1
    assert after.users.administrators == before.users.administrators

    # Files: one uploaded; it now exists as CORRUPTED rather than ACTIVE.
    assert after.files.total == before.files.total + 1
    assert after.files.corrupted == before.files.corrupted + 1
    assert after.files.active == before.files.active
    assert after.files.uploaded_last_24_hours == before.files.uploaded_last_24_hours + 1
    assert after.files.original_bytes == before.files.original_bytes + FIXTURE_BYTES
    assert after.files.stored_bytes == before.files.stored_bytes + FIXTURE_BYTES
    assert after.files.by_algorithm.get("AES-256-GCM", 0) == (
        before.files.by_algorithm.get("AES-256-GCM", 0) + 1
    )

    # Integrity: two checks, one of which failed.
    assert after.integrity.checks_last_24_hours == before.integrity.checks_last_24_hours + 2
    assert (
        after.integrity.failed_checks_last_24_hours
        == before.integrity.failed_checks_last_24_hours + 1
    )

    # Audit: the failed check is the newest FAIL event and names its actor, and nothing else.
    assert after.audit.events_total >= before.audit.events_total + 4
    assert after.audit.failures_last_24_hours >= before.audit.failures_last_24_hours + 1
    newest = after.audit.recent_failures[0]
    assert (newest.action, newest.result) == ("FILE_INTEGRITY_CHECKED", "FAIL")
    assert newest.actor_username == owner.username
    assert len(after.audit.recent_failures) <= 5


def test_conditional_counts_equal_a_plain_sql_count_however_many_rows_match(
    auth_mysql_engine: Engine,
) -> None:
    """`SUM(<boolean>)` read back through bool() reported 1 whenever the total was above zero."""
    from datetime import timedelta

    from sqlalchemy import text

    from app.core.time import to_second_resolution_utc, utc_now

    since = to_second_resolution_utc(utc_now() - timedelta(hours=24))
    with session_scope(auth_mysql_engine) as session:
        repository = AdminRepository(session)
        checks, failed = repository.integrity_check_counts_since(since)
        total, in_window, failures = repository.audit_counts(since)
        raw = session.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM integrity_checks WHERE created_at >= :s), "
                "(SELECT COUNT(*) FROM integrity_checks WHERE created_at >= :s AND result <> 'VALID'), "
                "(SELECT COUNT(*) FROM audit_logs), "
                "(SELECT COUNT(*) FROM audit_logs WHERE created_at >= :s), "
                "(SELECT COUNT(*) FROM audit_logs WHERE created_at >= :s AND result = 'FAIL')"
            ),
            {"s": since},
        ).one()

    assert (checks, failed, total, in_window, failures) == tuple(int(v) for v in raw)


def test_every_dashboard_query_runs_on_mysql_with_no_activity(auth_mysql_engine: Engine) -> None:
    admin = register_real_user(auth_mysql_engine, prefix="stats-admin-idle", role=SystemRole.ADMIN)

    stats = _stats(auth_mysql_engine, admin)

    assert stats.users.total >= 1 and stats.users.administrators >= 1
    assert stats.files.total == stats.files.active + stats.files.corrupted
    assert (
        stats.shares.active_shares >= 0 and stats.shares.files_shared <= stats.shares.active_shares
    )
    assert stats.generated_at.tzinfo is not None
