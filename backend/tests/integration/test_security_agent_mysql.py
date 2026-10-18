"""The security agent against real MySQL: the queries run, and a real tampering is reported.

The `_test` database is shared and permanent, so nothing asserts an absolute count: the test
performs real activity through the services the API uses, then looks for its own file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine
from tests.integration._concurrency_support import (
    active_recovery_key,
    file_service,
    fresh_ip,
    integration_settings,
    register_real_user,
    request_context,
    session_scope,
    upload_file,
)

from app.domain.enums import SystemRole
from app.domain.errors import InvalidCredentialsError
from app.services.auth_service import AuthService
from app.services.security_agent_service import SecurityAgentService

pytestmark = pytest.mark.integration


def test_a_really_tampered_file_is_reported_as_critical_with_its_backup_window(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    admin = register_real_user(auth_mysql_engine, prefix="agent-admin", role=SystemRole.ADMIN)
    owner = register_real_user(auth_mysql_engine, prefix="agent-owner")
    with active_recovery_key(auth_mysql_engine) as recovery:
        uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)

    def check() -> str:
        with session_scope(auth_mysql_engine) as session:
            return (
                file_service(session, tmp_path)
                .integrity_check(
                    actor=owner.actor(), file_id=uploaded.file_id, context=request_context()
                )
                .status
            )

    assert check() == "VALID"
    (stored,) = list((tmp_path / "objects").rglob("*.ciphertext"))
    stored.write_bytes(b"damaged on purpose" + stored.read_bytes()[18:])
    assert check() == "MODIFIED"

    with session_scope(auth_mysql_engine) as session:
        report = SecurityAgentService(db=session).report(actor=admin.actor(), window_hours=24)

    mine = [f for f in report.findings if f.file_id == uploaded.file_id]
    assert len(mine) == 1
    finding = mine[0]
    assert finding.priority == "CRITICAL" and finding.rule_id == "INTEGRITY_DAMAGE"
    assert "certainly hold the original" in finding.recommended_action  # a VALID check preceded it
    assert "Damage first seen" in " ".join(finding.evidence)
    assert report.counts.critical >= 1
    assert report.inputs.files_checkable >= 1 and report.inputs.audit_chain_entries_verified >= 1
    assert len(report.rules) == 13


def test_every_agent_query_runs_on_mysql_with_no_activity(auth_mysql_engine: Engine) -> None:
    admin = register_real_user(auth_mysql_engine, prefix="agent-idle", role=SystemRole.ADMIN)

    with session_scope(auth_mysql_engine) as session:
        report = SecurityAgentService(db=session).report(actor=admin.actor(), window_hours=168)

    assert report.generated_at.tzinfo is not None
    assert report.boundaries and all(rule.findings >= 0 for rule in report.rules)


@pytest.mark.parametrize(
    ("role", "priority"), [(SystemRole.USER, "HIGH"), (SystemRole.ADMIN, "CRITICAL")]
)
def test_real_failed_sign_ins_then_a_real_success_are_reported_as_guessing_that_worked(
    auth_mysql_engine: Engine, role: SystemRole, priority: str
) -> None:
    admin = register_real_user(
        auth_mysql_engine, prefix="agent-takeover-admin", role=SystemRole.ADMIN
    )
    victim = register_real_user(auth_mysql_engine, prefix="agent-takeover", role=role)
    settings = integration_settings()
    ip = fresh_ip()

    def sign_in(password: str) -> None:
        with session_scope(auth_mysql_engine) as session:
            AuthService(db=session, settings=settings).login(
                username=victim.username, password=password, context=request_context(ip_address=ip)
            )

    for attempt in range(5):  # under the account throttle's ten
        with pytest.raises(InvalidCredentialsError):
            sign_in(f"Wrong-{attempt}-{victim.password}")
    sign_in(victim.password)

    with session_scope(auth_mysql_engine) as session:
        report = SecurityAgentService(db=session, settings=settings).report(
            actor=admin.actor(), window_hours=24
        )

    mine = [
        f
        for f in report.findings
        if f.rule_id == "SIGN_IN_AFTER_GUESSING" and f.title.startswith(f"{victim.username} ")
    ]
    assert len(mine) == 1
    (finding,) = mine
    assert finding.priority == priority
    text = " ".join(finding.evidence)
    assert "5 against this account, 5 from the address that then signed in" in text
    assert f"from {ip}" in text
    assert ("(administrator)" in text) is (role is SystemRole.ADMIN)
