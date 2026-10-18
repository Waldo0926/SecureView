"""The administrator dashboard numbers: who may read them, how they are derived, and that
they stay numbers."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy.dialects import mysql

from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import AuthorizationError
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin_schema import AdminStatsOut
from app.services.admin_service import AdminService

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _actor(role: SystemRole) -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("22222222-2222-4222-8222-222222222222"),
        session_id=8,
        session_public_id=UUID("33333333-3333-4333-8333-333333333333"),
        role=role,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeStatsRepository:
    """Canned answers that also remember the cutoffs the service computed."""

    def __init__(self) -> None:
        self.cutoffs: dict[str, datetime] = {}

    def user_counts_by_status(self):
        return {"ACTIVE": 8, "DISABLED": 2, "DELETED": 3}

    def count_administrators(self):
        return 1

    def count_users_created_since(self, since):
        self.cutoffs["users_created"] = since
        return 4

    def count_users_signed_in_since(self, since):
        self.cutoffs["signed_in"] = since
        return 5

    def file_counts_by_status(self):
        return {"ACTIVE": 10, "CORRUPTED": 2, "DELETED": 6}

    def count_files_uploaded_since(self, since):
        self.cutoffs["uploaded"] = since
        return 3

    def stored_totals(self):
        return 1_000, 1_000

    def file_counts_by_algorithm(self):
        return {"AES-256-GCM": 9, "ChaCha20-Poly1305": 3}

    def share_counts(self):
        return 7, 4

    def integrity_check_counts_since(self, since):
        self.cutoffs["checks"] = since
        return 20, 1

    def count_pending_recovery_requests(self):
        return 2

    def audit_counts(self, since):
        self.cutoffs["audit"] = since
        return 500, 40, 6

    def recent_audit_failures(self, *, limit):
        assert limit == 5
        return [("AUTH_LOGIN_FAILED", "FAIL", datetime(2026, 10, 1, 11, 59), None)]


def _service(repository) -> AdminService:
    return AdminService(
        db=SimpleNamespace(),
        repository=repository,
        auth_repository=SimpleNamespace(),
        audit_service=SimpleNamespace(),
        clock=lambda: NOW,
    )


def test_a_non_administrator_is_refused_before_any_count_is_read() -> None:
    class Untouchable:
        def __getattr__(self, name: str):
            raise AssertionError(f"{name} must not be called for a non-administrator")

    for role in (SystemRole.USER, SystemRole.RECOVERY_OFFICER):
        with pytest.raises(AuthorizationError):
            _service(Untouchable()).platform_stats(actor=_actor(role))


def test_the_summary_is_assembled_from_the_counts() -> None:
    repository = FakeStatsRepository()

    stats = _service(repository).platform_stats(actor=_actor(SystemRole.ADMIN))

    assert stats.users.total == 13  # every row, deleted accounts included
    assert (stats.users.active, stats.users.disabled, stats.users.deleted) == (8, 2, 3)
    assert stats.users.administrators == 1
    assert stats.files.total == 12  # files that exist: active + corrupted, never deleted
    assert (stats.files.active, stats.files.corrupted, stats.files.deleted) == (10, 2, 6)
    assert stats.files.by_algorithm == {"AES-256-GCM": 9, "ChaCha20-Poly1305": 3}
    assert stats.shares.active_shares == 7 and stats.shares.files_shared == 4
    assert stats.integrity.failed_checks_last_24_hours == 1
    assert stats.recovery.pending_requests == 2
    assert stats.audit.failures_last_24_hours == 6
    assert stats.audit.recent_failures[0].action == "AUTH_LOGIN_FAILED"
    assert stats.audit.recent_failures[0].actor_username is None
    assert stats.generated_at == NOW


def test_windows_are_measured_back_from_now_in_naive_utc() -> None:
    repository = FakeStatsRepository()

    _service(repository).platform_stats(actor=_actor(SystemRole.ADMIN))

    day = (NOW - timedelta(hours=24)).replace(tzinfo=None)
    week = (NOW - timedelta(days=7)).replace(tzinfo=None)
    for name in ("signed_in", "uploaded", "checks", "audit"):
        assert repository.cutoffs[name] == day
    assert repository.cutoffs["users_created"] == week


def _walk_field_names(model: type[BaseModel]) -> set[str]:
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        annotation = field.annotation
        for candidate in (annotation, *getattr(annotation, "__args__", ())):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                names |= _walk_field_names(candidate)
    return names


def test_the_summary_has_no_field_that_could_carry_content_or_an_address() -> None:
    names = _walk_field_names(AdminStatsOut)

    forbidden = {
        "original_filename",
        "filename",
        "email",
        "ip_address",
        "user_agent",
        "metadata",
        "metadata_json",
        "public_key_pem",
        "wrapped_file_key",
        "nonce",
        "auth_tag",
    }
    assert names.isdisjoint(forbidden)
    assert "recent_failures" in names  # the one list carries only action, result, time, actor


# --- the SQL ------------------------------------------------------------------------------


class RecordingDb:
    """Captures every statement and answers with whatever shape the caller needs."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def _sql(self, statement) -> str:
        sql = str(
            statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        self.statements.append(sql)
        return sql

    def execute(self, statement):
        self._sql(statement)
        return _Rows()

    def scalar(self, statement):
        self._sql(statement)
        return 0


class _Rows:
    def __iter__(self):
        return iter(())

    def one(self):
        return (0, 0, 0)


def _sql_of(call) -> str:
    db = RecordingDb()
    call(AdminRepository(db))  # type: ignore[arg-type]
    assert len(db.statements) == 1
    return db.statements[0]


def test_stored_totals_ignore_deleted_files() -> None:
    sql = _sql_of(lambda repo: repo.stored_totals())

    assert "files.status != 'DELETED'" in sql
    assert (
        "sum(files.file_size_bytes)" in sql.lower()
        and "sum(files.encrypted_size_bytes)" in sql.lower()
    )


def test_share_counts_exclude_the_owners_own_grant_revoked_grants_and_deleted_files() -> None:
    sql = _sql_of(lambda repo: repo.share_counts())

    assert "file_access_grants.status = 'ACTIVE'" in sql
    assert "file_access_grants.user_id != files.owner_id" in sql
    assert "files.status != 'DELETED'" in sql


def test_recent_failures_select_four_columns_and_only_failures() -> None:
    sql = _sql_of(lambda repo: repo.recent_audit_failures(limit=5))

    select_list = sql.split("FROM", maxsplit=1)[0]
    assert "audit_logs.action" in select_list and "users.username" in select_list
    for private in ("ip_address", "user_agent", "metadata_json", "description", "resource_id"):
        assert private not in select_list
    assert "audit_logs.result = 'FAIL'" in sql
    assert "ORDER BY audit_logs.created_at DESC" in sql and "LIMIT 5" in sql


def test_pending_recovery_and_integrity_filters() -> None:
    assert "recovery_requests.status = 'PENDING'" in _sql_of(
        lambda repo: repo.count_pending_recovery_requests()
    )
    since = datetime(2026, 9, 30, 12, 0, 0)
    integrity = _sql_of(lambda repo: repo.integrity_check_counts_since(since))
    assert "integrity_checks.result != 'VALID'" in integrity
    assert "integrity_checks.created_at >= '2026-09-30 12:00:00'" in integrity


# --- the integrity report and the on-demand scan ------------------------------------------


class FakeIntegrityRepository:
    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.cutoff = None

    def integrity_coverage(self, since):
        self.cutoff = since
        return 10, 3, 6, datetime(2026, 10, 1, 4, 30)

    def damaged_files(self, *, limit):
        return self.rows[:limit]


def _damaged(n: int, *, status="CORRUPTED", result="MODIFIED"):
    return SimpleNamespace(
        file_uuid=f"00000000-0000-4000-8000-{n:012d}",
        original_filename=f"report-{n}.pdf",
        status=status,
        owner_username="alice",
        last_result=result,
        last_message="The encrypted object does not match",
        last_checked_at=datetime(2026, 10, 1, 9, 0),
    )


def test_the_integrity_report_is_refused_to_a_non_administrator() -> None:
    class Untouchable:
        def __getattr__(self, name: str):
            raise AssertionError(f"{name} must not be called for a non-administrator")

    with pytest.raises(AuthorizationError):
        _service(Untouchable()).integrity_report(actor=_actor(SystemRole.USER), limit=10)


def test_the_integrity_report_lists_damage_and_how_much_was_checked() -> None:
    repository = FakeIntegrityRepository(
        [_damaged(1), _damaged(2, status="ACTIVE", result="MISSING")]
    )

    report = _service(repository).integrity_report(actor=_actor(SystemRole.ADMIN), limit=10)

    assert report.coverage.candidates == 10
    assert report.coverage.never_checked == 3
    assert report.coverage.checked_last_24_hours == 6
    assert report.coverage.last_sweep_at is not None
    assert [(f.original_filename, f.status, f.last_result) for f in report.damaged] == [
        ("report-1.pdf", "CORRUPTED", "MODIFIED"),
        ("report-2.pdf", "ACTIVE", "MISSING"),
    ]
    assert report.has_more is False
    assert repository.cutoff == (NOW - timedelta(hours=24)).replace(tzinfo=None)


def test_the_integrity_report_says_when_there_is_more_than_one_page() -> None:
    repository = FakeIntegrityRepository([_damaged(n) for n in range(1, 5)])

    report = _service(repository).integrity_report(actor=_actor(SystemRole.ADMIN), limit=3)

    assert len(report.damaged) == 3
    assert report.has_more is True


def test_the_integrity_report_names_no_key_material_or_address() -> None:
    from app.schemas.admin_schema import AdminIntegrityReportOut

    names = _walk_field_names(AdminIntegrityReportOut)

    assert names.isdisjoint(
        {
            "email",
            "ip_address",
            "user_agent",
            "wrapped_file_key",
            "nonce",
            "auth_tag",
            "storage_object_key",
        }
    )


def test_a_scan_is_refused_to_a_non_administrator_before_it_reads_anything() -> None:
    class Untouchable:
        def sweep(self, **_):
            raise AssertionError("sweep must not run for a non-administrator")

    service = AdminService(
        db=SimpleNamespace(),
        repository=SimpleNamespace(),
        auth_repository=SimpleNamespace(),
        audit_service=SimpleNamespace(),
        integrity_service=Untouchable(),
        clock=lambda: NOW,
    )

    with pytest.raises(AuthorizationError):
        service.scan_integrity(
            actor=_actor(SystemRole.USER), context=None, limit=5, budget_seconds=1.0
        )


def test_a_scan_runs_the_sweep_as_the_administrator_and_reports_counts() -> None:
    from app.services.integrity_service import SweepSummary

    calls = []

    class FakeIntegrity:
        def sweep(self, **kwargs):
            calls.append(kwargs)
            return SweepSummary(
                scanned=4,
                valid=3,
                modified=1,
                candidates=9,
                stopped_early=True,
                damaged_file_ids=["00000000-0000-4000-8000-000000000001"],
            )

    service = AdminService(
        db=SimpleNamespace(),
        repository=SimpleNamespace(),
        auth_repository=SimpleNamespace(),
        audit_service=SimpleNamespace(),
        integrity_service=FakeIntegrity(),
        clock=lambda: NOW,
    )

    result = service.scan_integrity(
        actor=_actor(SystemRole.ADMIN), context="ctx", limit=50, budget_seconds=20.0
    )

    assert calls == [{"actor_user_id": 7, "context": "ctx", "limit": 50, "budget_seconds": 20.0}]
    assert (result.scanned, result.valid, result.damaged, result.candidates) == (4, 3, 1, 9)
    assert result.stopped_early is True
    assert len(result.damaged_file_ids) == 1


def test_the_damaged_list_covers_corrupted_files_and_unreadable_objects_but_never_deleted_ones() -> (
    None
):
    sql = _sql_of(lambda repo: repo.damaged_files(limit=11))

    assert "files.status != 'DELETED'" in sql
    assert "files.status = 'CORRUPTED'" in sql
    assert "integrity_checks.result IN ('MODIFIED', 'MISSING', 'ERROR')" in sql
    assert re.search(r"max\(integrity_checks_\d+\.id\)", sql.lower())  # the newest check per file
    assert "LIMIT 11" in sql
    select_list = sql.split("FROM", maxsplit=1)[0]
    for private in ("iv", "auth_tag", "encrypted_manifest", "storage_object_key"):
        assert f"files.{private}" not in select_list
    assert "users.password_hash" not in select_list and "users.email" not in select_list


def test_the_scan_order_puts_never_checked_files_first_and_skips_deleted_ones() -> None:
    from app.repositories.file_repository import FileRepository

    db = RecordingDb()
    db.scalars = lambda statement: (db._sql(statement), iter(()))[1]  # type: ignore[method-assign]
    FileRepository(db).list_scan_candidates(limit=7)  # type: ignore[arg-type]

    sql = db.statements[0]
    assert "files.status IN ('ACTIVE', 'CORRUPTED')" in sql
    assert "max(integrity_checks.created_at)" in sql.lower()
    assert "IS NOT NULL" in sql and "LIMIT 7" in sql


def test_conditional_counts_sum_a_case_not_a_boolean() -> None:
    """A Boolean-typed SUM is coerced through bool() on the way back, so 7 failures read as 1."""
    since = datetime(2026, 9, 30, 12, 0, 0)

    integrity = _sql_of(lambda repo: repo.integrity_check_counts_since(since))
    audit = _sql_of(lambda repo: repo.audit_counts(since))

    assert "CASE WHEN (integrity_checks.result != 'VALID') THEN 1 ELSE 0 END" in integrity
    assert audit.count("CASE WHEN") == 2
    assert "sum(audit_logs.created_at >=" not in audit.lower()
