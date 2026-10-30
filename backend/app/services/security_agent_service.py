from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.time import to_api_utc, to_database_utc, to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext
from app.domain.enums import LoginThrottleScope, SystemRole, UserStatus
from app.domain.errors import AuthorizationError
from app.repositories.admin_repository import AdminRepository
from app.repositories.agent_repository import AgentRepository, DamagedFileHistory
from app.schemas.agent_schema import (
    AgentCountsOut,
    AgentFindingOut,
    AgentInputSummaryOut,
    AgentReportOut,
    AgentRuleOut,
)
from app.services.audit_query_service import AuditQueryService
from app.services.security_agent_rules import (
    RECOVERY_PENDING_AFTER,
    AgentInputs,
    DamagedFile,
    Event,
    Priority,
    evaluate,
)

BOUNDARIES = [
    "Read-only: the agent never changes a file, an account or a setting, and cannot run a "
    "recovery. It recommends; an administrator acts.",
    "Metadata only: it reads event types, times, counts, account names, source addresses and "
    "file identifiers. It never sees file contents, keys, passphrases or ciphertext.",
    "Rule-based: every finding comes from a named rule with a stated threshold. No model is "
    "asked to judge anything and nothing is sent outside the server.",
    "It reports what the platform recorded. It cannot see an attack that left no audit event, "
    "and a quiet report is not proof that nothing happened.",
]

_WATCHED = {
    "login": "AUTH_LOGIN_FAILED",
    "login_ok": "AUTH_LOGIN_SUCCEEDED",
    "replay": "AUTH_REFRESH_REPLAY_DETECTED",
    "download": "FILE_DOWNLOAD_AUTHORIZED",
    "share": "FILE_SHARED",
    "upload": "FILE_UPLOADED",
    "password": "AUTH_PASSWORD_CHANGE_FAILED",
    # Closing an account asks for the current password too, through the same throttle, so a
    # guess made there is the same signal as one made on the change-password form.
    "deletion_password": "ACCOUNT_DELETION_PASSWORD_FAILED",
    "recovery": "RECOVERY_REQUEST_EXECUTED",
}


def current_failure_run(
    history: DamagedFileHistory,
) -> tuple[datetime | None, datetime | None, str | None]:
    """(last intact check, when the current run of failing checks began, newest failing result).

    `checks` is newest first. The current run is the failing checks at the top of it; the first
    VALID check below them is the last time the object was known good.
    """
    run_began: datetime | None = None
    newest_result: str | None = None
    last_valid: datetime | None = None
    in_run = True
    for result, at in history.checks:
        if in_run and result != "VALID":
            run_began = at
            newest_result = newest_result or result
            continue
        in_run = False
        if result == "VALID":
            last_valid = at
            break
    return last_valid, run_began, newest_result


class SecurityAgentService:
    def __init__(
        self,
        *,
        db: Session,
        repository: AgentRepository | None = None,
        admin_repository: AdminRepository | None = None,
        audit_query: AuditQueryService | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.repository = repository or AgentRepository(db)
        self.admin_repository = admin_repository or AdminRepository(db)
        self.audit_query = audit_query or AuditQueryService(db=db)
        self.settings = settings or get_settings()
        self.clock = clock

    def report(self, *, actor: ActorContext, window_hours: int) -> AgentReportOut:
        """The report for the Security agent tab. Administrators only."""
        if actor.role is not SystemRole.ADMIN:
            raise AuthorizationError()
        return self._build(
            window_hours=window_hours,
            verify_chain=lambda: self.audit_query.verify_chain(actor=actor),
        )

    def report_for_scheduled_check(self, *, window_hours: int) -> AgentReportOut:
        """The same report for the daily check (scripts/security_agent_check.py).

        That script runs on the server as the service account, so there is no signed-in actor to
        check; the audit chain is verified through the clearly named trusted-job path instead.
        No HTTP route calls this.
        """
        return self._build(
            window_hours=window_hours,
            verify_chain=self.audit_query.verify_chain_for_trusted_job,
        )

    def _throttle_policy(self) -> str:
        s = self.settings
        window = s.AUTH_LOGIN_WINDOW_SECONDS // 60
        return (
            f"an account is blocked for {s.AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS // 60} minutes after "
            f"{s.AUTH_LOGIN_ACCOUNT_MAX_FAILURES} failures in {window} minutes, an address for "
            f"{s.AUTH_LOGIN_IP_BLOCK_SECONDS // 60} minutes after {s.AUTH_LOGIN_IP_MAX_FAILURES}"
        )

    def _build(
        self,
        *,
        window_hours: int,
        verify_chain: Callable[[], dict[str, int | bool | str | None]],
    ) -> AgentReportOut:
        now = self.clock()
        window = timedelta(hours=window_hours)
        since = to_second_resolution_utc(now - window)

        rows, capped = self.repository.audit_events(list(_WATCHED.values()), since=since)
        by_action: dict[str, list[Event]] = {action: [] for action in _WATCHED.values()}
        for row in rows:
            by_action[row.action].append(
                Event(
                    at=row.created_at,
                    actor=row.actor_username,
                    source=row.ip_address,
                    admin=row.actor_role == SystemRole.ADMIN,
                    # No actor row (a failed sign-in at a name that does not exist) is not an
                    # inactive account, so only a known status other than ACTIVE counts.
                    active=row.actor_status is None or row.actor_status == UserStatus.ACTIVE,
                )
            )

        damaged: list[DamagedFile] = []
        for history in self.repository.damaged_file_histories(limit=50):
            last_valid, run_began, newest = current_failure_run(history)
            damaged.append(
                DamagedFile(
                    file_id=history.file_uuid,
                    filename=history.filename,
                    owner=history.owner_username,
                    status=history.status,
                    last_result=newest,
                    uploaded_at=history.uploaded_at,
                    last_valid_at=last_valid,
                    first_failure_at=run_began,
                )
            )

        candidates, never_checked, _, last_sweep = self.admin_repository.integrity_coverage(since)
        chain = verify_chain()
        blocks = self.repository.active_login_blocks(to_database_utc(now))

        inputs = AgentInputs(
            now=now.replace(tzinfo=None) if now.tzinfo else now,
            window=window,
            login_failures=by_action[_WATCHED["login"]],
            login_successes=by_action[_WATCHED["login_ok"]],
            refresh_replays=by_action[_WATCHED["replay"]],
            downloads=by_action[_WATCHED["download"]],
            shares=by_action[_WATCHED["share"]],
            uploads=by_action[_WATCHED["upload"]],
            password_failures=(
                by_action[_WATCHED["password"]] + by_action[_WATCHED["deletion_password"]]
            ),
            recoveries_executed=by_action[_WATCHED["recovery"]],
            recoveries_pending_old=self.repository.count_recovery_requests_pending_before(
                to_second_resolution_utc(now - RECOVERY_PENDING_AFTER)
            ),
            damaged=damaged,
            chain_valid=bool(chain["valid"]),
            chain_first_invalid_position=chain["first_invalid_position"],  # type: ignore[arg-type]
            chain_checked_entries=int(chain["checked_entries"] or 0),
            last_sweep_at=last_sweep,
            checkable_files=candidates,
            never_checked_files=never_checked,
            throttled_addresses=blocks.get(LoginThrottleScope.IP, 0),
            throttled_accounts=blocks.get(LoginThrottleScope.ACCOUNT, 0),
            throttle_policy=self._throttle_policy(),
        )
        findings, outcomes = evaluate(inputs)

        counts = {priority: 0 for priority in Priority}
        for finding in findings:
            counts[finding.priority] += 1
        return AgentReportOut(
            generated_at=to_api_utc(now),
            window_hours=window_hours,
            counts=AgentCountsOut(
                critical=counts[Priority.CRITICAL],
                high=counts[Priority.HIGH],
                medium=counts[Priority.MEDIUM],
                low=counts[Priority.LOW],
            ),
            findings=[
                AgentFindingOut(
                    rule_id=f.rule_id,
                    priority=f.priority.value,
                    title=f.title,
                    summary=f.summary,
                    evidence=list(f.evidence),
                    recommended_action=f.recommended_action,
                    file_id=UUID(f.file_id) if f.file_id else None,
                )
                for f in findings
            ],
            rules=[
                AgentRuleOut(
                    rule_id=o.info.rule_id,
                    name=o.info.name,
                    watches=o.info.watches,
                    threshold=o.info.threshold,
                    findings=o.findings,
                )
                for o in outcomes
            ],
            inputs=AgentInputSummaryOut(
                audit_events_read=len(rows),
                event_types_capped=capped,
                files_checkable=candidates,
                files_never_checked=never_checked,
                audit_chain_entries_verified=int(chain["checked_entries"] or 0),
                last_scan_at=to_api_utc(last_sweep),
            ),
            boundaries=BOUNDARIES,
        )
