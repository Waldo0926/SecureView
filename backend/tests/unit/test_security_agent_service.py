"""Gathering the evidence for the security agent: the right window, the right grouping, no write."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import mysql

from app.core.config import Settings
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import AuthorizationError
from app.repositories.agent_repository import (
    AgentRepository,
    AuditEventRow,
    DamagedFileHistory,
)
from app.services.security_agent_service import (
    BOUNDARIES,
    SecurityAgentService,
    current_failure_run,
)

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)


def _actor(role: SystemRole = SystemRole.ADMIN) -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("22222222-2222-4222-8222-222222222222"),
        session_id=8,
        session_public_id=UUID("33333333-3333-4333-8333-333333333333"),
        role=role,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeAgentRepository:
    def __init__(self, events=(), histories=(), pending_old=0, blocks=None) -> None:
        self.events = list(events)
        self.histories = list(histories)
        self.pending_old = pending_old
        self.blocks = blocks or {}
        self.asked: dict = {}

    def active_login_blocks(self, now):
        self.asked["blocks_at"] = now
        return self.blocks

    def audit_events(self, actions, *, since):
        self.asked["actions"] = set(actions)
        self.asked["since"] = since
        return [e for e in self.events if e.action in actions and e.created_at >= since], []

    def count_recovery_requests_pending_before(self, cutoff):
        self.asked["recovery_cutoff"] = cutoff
        return self.pending_old

    def damaged_file_histories(self, *, limit):
        return self.histories[:limit]


class FakeAdminRepository:
    def __init__(self, last_sweep=NAIVE_NOW - timedelta(hours=2), candidates=5, never=0) -> None:
        self.value = (candidates, never, 3, last_sweep)

    def integrity_coverage(self, since):
        return self.value


class FakeAuditQuery:
    def __init__(self, valid=True, position=None, checked=120) -> None:
        self.result = {
            "valid": valid,
            "status": "VALID" if valid else "INVALID",
            "checked_entries": checked,
            "first_invalid_position": position,
        }
        self.calls: list[str] = []

    def verify_chain(self, *, actor):
        self.calls.append("admin")
        return self.result

    def verify_chain_for_trusted_job(self):
        self.calls.append("trusted-job")
        return self.result


def _service(repository=None, admin=None, audit=None) -> SecurityAgentService:
    return SecurityAgentService(
        db=SimpleNamespace(),
        repository=repository or FakeAgentRepository(),
        admin_repository=admin or FakeAdminRepository(),
        audit_query=audit or FakeAuditQuery(),
        # The default throttle policy, whatever the environment running the tests sets.
        settings=Settings(
            _env_file=None, APP_ENV="test", SECRET_KEY="agent-unit-test-secret-key-32-chars"
        ),
        clock=lambda: NOW,
    )


def _failures(count, *, ip="203.0.113.9", user="alice", seconds=10):
    return [
        AuditEventRow(
            "AUTH_LOGIN_FAILED",
            NAIVE_NOW - timedelta(minutes=30) + timedelta(seconds=seconds * i),
            user,
            ip,
        )
        for i in range(count)
    ]


def test_only_an_administrator_can_ask_and_nothing_is_read_for_anyone_else() -> None:
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"{name} must not be called for a non-administrator")

    service = SecurityAgentService(
        db=SimpleNamespace(),
        repository=Untouchable(),
        admin_repository=Untouchable(),
        audit_query=Untouchable(),
        clock=lambda: NOW,
    )

    for role in (SystemRole.USER, SystemRole.RECOVERY_OFFICER):
        with pytest.raises(AuthorizationError):
            service.report(actor=_actor(role), window_hours=24)


def test_a_quiet_platform_gives_an_empty_report_that_still_shows_what_was_read() -> None:
    report = _service().report(actor=_actor(), window_hours=24)

    assert report.findings == []
    assert report.counts.model_dump() == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    assert report.inputs.audit_events_read == 0
    assert report.inputs.files_checkable == 5 and report.inputs.audit_chain_entries_verified == 120
    assert report.inputs.last_scan_at is not None
    assert len(report.rules) == 13 and all(rule.findings == 0 for rule in report.rules)
    assert report.boundaries == BOUNDARIES


def test_the_window_is_measured_back_from_now_and_only_watched_events_are_requested() -> None:
    repository = FakeAgentRepository()

    _service(repository).report(actor=_actor(), window_hours=48)

    assert repository.asked["since"] == (NOW - timedelta(hours=48)).replace(tzinfo=None)
    assert repository.asked["actions"] == {
        "AUTH_LOGIN_FAILED",
        "AUTH_LOGIN_SUCCEEDED",
        "AUTH_REFRESH_REPLAY_DETECTED",
        "FILE_DOWNLOAD_AUTHORIZED",
        "FILE_SHARED",
        "FILE_UPLOADED",
        "AUTH_PASSWORD_CHANGE_FAILED",
        "ACCOUNT_DELETION_PASSWORD_FAILED",
        "RECOVERY_REQUEST_EXECUTED",
    }
    assert repository.asked["recovery_cutoff"] == (NOW - timedelta(hours=24)).replace(tzinfo=None)
    assert repository.asked["blocks_at"] == NAIVE_NOW


def test_a_burst_of_failed_sign_ins_becomes_a_ranked_finding_with_an_action() -> None:
    report = _service(FakeAgentRepository(events=_failures(14))).report(
        actor=_actor(), window_hours=24
    )

    # One address guessing one account is one incident, reported once, naming the account.
    assert report.counts.medium == 1
    source = next(f for f in report.findings if f.rule_id == "LOGIN_GUESSING_SOURCE")
    assert "Accounts tried: alice" in source.evidence
    assert source.priority == "MEDIUM" and "203.0.113.9" in source.title
    assert "fail2ban" in source.recommended_action
    assert report.inputs.audit_events_read == 14


def test_wrong_passwords_on_the_close_account_form_count_as_password_guessing() -> None:
    # Both forms ask for the current password through one shared throttle, so the rule sees
    # them together: three wrong guesses on one and two on the other make the five it needs.
    def failure(action: str, minute: int) -> AuditEventRow:
        return AuditEventRow(action, NAIVE_NOW - timedelta(minutes=10 - minute), "bob", None)

    events = [failure("AUTH_PASSWORD_CHANGE_FAILED", m) for m in range(3)] + [
        failure("ACCOUNT_DELETION_PASSWORD_FAILED", m) for m in range(3, 5)
    ]

    report = _service(FakeAgentRepository(events=events)).report(actor=_actor(), window_hours=24)

    (finding,) = [f for f in report.findings if f.rule_id == "PASSWORD_CHANGE_GUESSING"]
    assert finding.priority == "MEDIUM"
    assert "bob" in finding.title and "5" in finding.title


def test_events_outside_the_window_are_ignored() -> None:
    old = [
        AuditEventRow(
            "AUTH_LOGIN_FAILED", NAIVE_NOW - timedelta(days=3, seconds=i), "alice", "198.51.100.5"
        )
        for i in range(40)
    ]

    report = _service(FakeAgentRepository(events=old)).report(actor=_actor(), window_hours=24)

    assert report.findings == [] and report.inputs.audit_events_read == 0


def test_a_failure_run_is_read_from_the_newest_checks_down() -> None:
    history = DamagedFileHistory(
        file_uuid="11111111-1111-4111-8111-111111111111",
        filename="a.pdf",
        owner_username="alice",
        status="CORRUPTED",
        uploaded_at=NAIVE_NOW - timedelta(days=9),
        checks=(
            ("MODIFIED", NAIVE_NOW - timedelta(hours=1)),
            ("MODIFIED", NAIVE_NOW - timedelta(hours=5)),  # the run began here
            ("VALID", NAIVE_NOW - timedelta(hours=29)),  # last known good
            ("MODIFIED", NAIVE_NOW - timedelta(days=4)),  # an older, healed episode
            ("VALID", NAIVE_NOW - timedelta(days=6)),
        ),
    )

    last_valid, began, newest = current_failure_run(history)

    assert last_valid == NAIVE_NOW - timedelta(hours=29)
    assert began == NAIVE_NOW - timedelta(hours=5)
    assert newest == "MODIFIED"


def test_a_file_with_no_passing_check_has_no_known_good_time() -> None:
    history = DamagedFileHistory(
        "x", "a.pdf", "alice", "CORRUPTED", NAIVE_NOW, (("MISSING", NAIVE_NOW),)
    )

    assert current_failure_run(history) == (None, NAIVE_NOW, "MISSING")
    assert current_failure_run(DamagedFileHistory("x", "a", "b", "CORRUPTED", NAIVE_NOW, ())) == (
        None,
        None,
        None,
    )


def test_a_damaged_file_and_a_broken_chain_are_critical_and_listed_first() -> None:
    history = DamagedFileHistory(
        file_uuid="11111111-1111-4111-8111-111111111111",
        filename="report.pdf",
        owner_username="alice",
        status="CORRUPTED",
        uploaded_at=NAIVE_NOW - timedelta(days=9),
        checks=(
            ("MODIFIED", NAIVE_NOW - timedelta(hours=2)),
            ("VALID", NAIVE_NOW - timedelta(days=1)),
        ),
    )
    service = _service(
        FakeAgentRepository(events=_failures(14), histories=[history]),
        audit=FakeAuditQuery(valid=False, position=57, checked=56),
    )

    report = service.report(actor=_actor(), window_hours=24)

    assert report.counts.critical == 2
    assert [f.priority for f in report.findings][:2] == ["CRITICAL", "CRITICAL"]
    damage = next(f for f in report.findings if f.rule_id == "INTEGRITY_DAMAGE")
    assert damage.file_id == UUID("11111111-1111-4111-8111-111111111111")
    assert "certainly hold the original" in damage.recommended_action
    chain = next(f for f in report.findings if f.rule_id == "AUDIT_CHAIN_BROKEN")
    assert "position 57" in " ".join(chain.evidence)


def test_a_sign_in_after_guessing_carries_the_role_through_to_a_critical_finding() -> None:
    success = AuditEventRow(
        "AUTH_LOGIN_SUCCEEDED", NAIVE_NOW - timedelta(minutes=29), "alice", "203.0.113.9", "ADMIN"
    )

    report = _service(FakeAgentRepository(events=[*_failures(6), success])).report(
        actor=_actor(), window_hours=24
    )

    takeover = next(f for f in report.findings if f.rule_id == "SIGN_IN_AFTER_GUESSING")
    assert takeover.priority == "CRITICAL" and "(administrator)" in takeover.evidence[0]
    assert report.findings[0] is takeover


def test_throttle_blocks_are_read_by_scope_and_carry_the_configured_policy() -> None:
    from app.domain.enums import LoginThrottleScope

    repository = FakeAgentRepository(
        blocks={LoginThrottleScope.IP: 1, LoginThrottleScope.ACCOUNT: 2}
    )

    report = _service(repository).report(actor=_actor(), window_hours=24)

    (finding,) = report.findings
    assert finding.rule_id == "SIGN_IN_THROTTLE_ACTIVE" and finding.priority == "MEDIUM"
    assert (
        "Throttle policy: an account is blocked for 5 minutes after 10 failures in 15 minutes, "
        "an address for 15 minutes after 500"
    ) in finding.evidence


def test_the_scheduled_check_needs_no_actor_and_uses_the_trusted_job_chain_path() -> None:
    audit = FakeAuditQuery()

    report = _service(
        FakeAgentRepository(events=_failures(14)), audit=audit
    ).report_for_scheduled_check(window_hours=24)

    assert audit.calls == ["trusted-job"]
    assert report.counts.medium == 1 and report.window_hours == 24
    # And the administrator route still goes through the checked path.
    _service(audit=audit).report(actor=_actor(), window_hours=24)
    assert audit.calls == ["trusted-job", "admin"]


def test_no_http_route_reaches_the_unchecked_entry_points() -> None:
    routers = Path(__file__).resolve().parents[2] / "app" / "api"
    source = "\n".join(path.read_text() for path in routers.rglob("*.py"))

    assert "verify_chain_for_trusted_job" not in source
    assert "report_for_scheduled_check" not in source


def test_a_stale_scan_is_reported_from_the_coverage_figures() -> None:
    admin = FakeAdminRepository(last_sweep=None, candidates=4, never=4)

    report = _service(admin=admin).report(actor=_actor(), window_hours=24)

    assert [f.rule_id for f in report.findings] == ["SCAN_NOT_RUNNING"]
    assert report.inputs.last_scan_at is None


# --- the SQL: read-only, and metadata only --------------------------------------------------


class _Db:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def _record(self, statement) -> str:
        sql = str(
            statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        )
        self.statements.append(sql)
        return sql

    def execute(self, statement):
        self._record(statement)

        class _Rows(list):
            def all(self):
                return []

        return _Rows()

    def scalar(self, statement):
        self._record(statement)
        return 0


def test_the_event_query_selects_six_columns_and_never_metadata_or_user_agents() -> None:
    db = _Db()
    AgentRepository(db).audit_events(["AUTH_LOGIN_FAILED"], since=NAIVE_NOW)  # type: ignore[arg-type]

    sql = db.statements[0]
    select_list = sql.split("FROM", maxsplit=1)[0]
    assert "audit_logs.action" in select_list and "users.username" in select_list
    assert "audit_logs.ip_address" in select_list
    for private in (
        "metadata_json",
        "user_agent",
        "description",
        "resource_id",
        "password_hash",
        "email",
    ):
        assert private not in select_list
    assert "audit_logs.action = 'AUTH_LOGIN_FAILED'" in sql
    assert "audit_logs.created_at >= " in sql and "LIMIT 5000" in sql
    assert "users.`role`" in select_list and "users.status" in select_list


def test_the_throttle_query_counts_blocks_and_never_selects_the_hashed_keys() -> None:
    db = _Db()
    blocks = AgentRepository(db).active_login_blocks(NAIVE_NOW)  # type: ignore[arg-type]

    sql = db.statements[0]
    select_list = sql.split("FROM", maxsplit=1)[0]
    assert "count(*)" in select_list and "key_hash" not in select_list
    assert "auth_login_throttles.blocked_until > " in sql and "GROUP BY" in sql
    assert "'IP'" in sql and "'ACCOUNT'" in sql and "REAUTH" not in sql
    assert set(blocks.values()) == {0}


def test_each_event_type_has_its_own_read_cap_so_one_flood_cannot_hide_another() -> None:
    db = _Db()
    rows, capped = AgentRepository(db).audit_events(  # type: ignore[arg-type]
        ["FILE_DOWNLOAD_AUTHORIZED", "AUTH_LOGIN_FAILED"], since=NAIVE_NOW
    )

    assert len(db.statements) == 2
    assert all("LIMIT 5000" in sql for sql in db.statements)
    assert rows == [] and capped == []


def test_the_damaged_file_query_never_selects_keys_nonces_or_ciphertext_columns() -> None:
    db = _Db()
    AgentRepository(db).damaged_file_histories(limit=50)  # type: ignore[arg-type]

    sql = db.statements[0]
    select_list = sql.split("FROM", maxsplit=1)[0]
    for private in ("iv", "auth_tag", "encrypted_manifest", "storage_object_key", "password_hash"):
        assert f".{private}" not in select_list
    assert "files.status != 'DELETED'" in sql


def test_the_agent_modules_have_no_database_write_path() -> None:
    import inspect
    import re

    from app.repositories import agent_repository
    from app.services import security_agent_rules, security_agent_service

    # Only reads may be called on the session. A set's .add() is not a database write.
    write = re.compile(r"self\.db\.(?!execute\b|scalar\b|scalars\b)\w+|\b(insert|update|delete)\(")
    assert write.search("self.db.add(row)") and write.search("self.db.commit()")
    assert not write.search("seen.add(x)") and not write.search("self.db.execute(q)")
    for module in (agent_repository, security_agent_rules, security_agent_service):
        source = inspect.getsource(module)
        assert not write.search(source), f"{module.__name__} can write to the database"
        assert "AuditLogService" not in source, f"{module.__name__} could append to the audit log"

    # The daily check script holds its session as `db`, and must only hand it to the agent.
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "security_agent_check.py"
    ).read_text()
    script = script.replace("sys.path.insert(0,", "")  # the import-path line, not a database write
    assert not write.search(script), "the daily check script can write to the database"
    assert re.search(r"\bdb\.\w+", script) is None, "the daily check script uses the session itself"
    assert "AuditLogService" not in script and "commit" not in script


def test_an_account_closed_since_its_burst_gets_advice_that_fits_a_closed_account() -> None:
    # The 2026-10-09 load test: throwaway accounts uploaded hundreds of files and were then
    # deleted, so the next morning's report named "deleted-…" accounts and told the
    # administrator to disable them. The status column is what lets the rule say otherwise.
    at = NAIVE_NOW - timedelta(minutes=30)
    uploads = [
        AuditEventRow(
            "FILE_UPLOADED",
            at + timedelta(seconds=i),
            "deleted-2674f2de84b34c308f261034489c8308",
            "203.0.113.9",
            "USER",
            "DELETED",
        )
        for i in range(120)
    ]
    still_open = [
        AuditEventRow("FILE_UPLOADED", at + timedelta(seconds=i), "bob", "203.0.113.9", "USER")
        for i in range(120)
    ]

    report = _service(FakeAgentRepository(events=uploads + still_open)).report(
        actor=_actor(), window_hours=24
    )

    open_, closed = sorted(
        (f for f in report.findings if f.rule_id == "UPLOAD_BURST"), key=lambda f: f.title
    )
    assert closed.title.startswith("deleted-") and closed.priority == "HIGH"
    assert any("not active now" in line for line in closed.evidence)
    assert "nothing to switch off" in closed.recommended_action
    assert "disable the account" not in closed.recommended_action
    assert open_.title.startswith("bob") and "disable the account" in open_.recommended_action
    assert not any("not active now" in line for line in open_.evidence)
