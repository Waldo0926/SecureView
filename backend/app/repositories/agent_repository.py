from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app.domain.enums import LoginThrottleScope
from app.models.audit_log import AuditLog
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.file import File
from app.models.integrity_check import IntegrityCheck
from app.models.recovery_request import RecoveryRequest
from app.models.user import User

# A runaway log must not turn one report into an unbounded read. The cap is per event type: with
# one shared cap, a flood of one kind (a bulk download, say) pushed every other kind out of the
# read, so a burst of failed sign-ins in the same window could simply not be seen. Within a type
# the newest events win, because a burst that is still going on is the one worth seeing.
EVENT_READ_LIMIT_PER_ACTION = 5_000


@dataclass(frozen=True, slots=True)
class AuditEventRow:
    action: str
    created_at: datetime
    actor_username: str | None
    ip_address: str | None
    actor_role: str | None = None
    # ACTIVE, DISABLED or DELETED. A burst from an account that has since been closed needs
    # different advice from one that is still open ("disable it" is no use for a deleted account).
    actor_status: str | None = None


@dataclass(frozen=True, slots=True)
class DamagedFileHistory:
    file_uuid: str
    filename: str
    owner_username: str
    status: str
    uploaded_at: datetime
    # Newest first: (result, when). The service reads the current run of failures off the top.
    checks: tuple[tuple[str, datetime], ...]


class AgentRepository:
    """Read-only queries for the security agent. It writes nothing and returns metadata only.

    Nothing here selects file contents, keys, ciphertext, request bodies, user agents or
    audit metadata: event type, time, account name and role, and source address are all the
    rules use. From the sign-in throttle it reads counts only, never the hashed keys.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def audit_events(
        self, actions: Sequence[str], *, since: datetime
    ) -> tuple[list[AuditEventRow], list[str]]:
        """The watched events in the window, and which actions hit the read cap."""
        rows: list[AuditEventRow] = []
        capped: list[str] = []
        for action in actions:
            batch = [
                AuditEventRow(*row)
                for row in self.db.execute(
                    select(
                        AuditLog.action,
                        AuditLog.created_at,
                        User.username,
                        AuditLog.ip_address,
                        User.role,
                        User.status,
                    )
                    .outerjoin(User, User.id == AuditLog.actor_user_id)
                    .where(AuditLog.action == action, AuditLog.created_at >= since)
                    .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                    .limit(EVENT_READ_LIMIT_PER_ACTION)
                )
            ]
            if len(batch) >= EVENT_READ_LIMIT_PER_ACTION:
                capped.append(action)
            rows.extend(batch)
        return rows, capped

    def active_login_blocks(self, now: datetime) -> dict[LoginThrottleScope, int]:
        """How many sign-in throttle buckets are blocked at `now`, per scope (address, account)."""
        scopes = (LoginThrottleScope.IP, LoginThrottleScope.ACCOUNT)
        counts = {scope: 0 for scope in scopes}
        for scope, count in self.db.execute(
            select(AuthLoginThrottle.scope, func.count())
            .where(AuthLoginThrottle.scope.in_(scopes), AuthLoginThrottle.blocked_until > now)
            .group_by(AuthLoginThrottle.scope)
        ):
            counts[LoginThrottleScope(scope)] = int(count)
        return counts

    def count_recovery_requests_pending_before(self, cutoff: datetime) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(RecoveryRequest)
                .where(RecoveryRequest.status == "PENDING", RecoveryRequest.created_at < cutoff)
            )
            or 0
        )

    def damaged_file_histories(self, *, limit: int) -> list[DamagedFileHistory]:
        """Files that are CORRUPTED or whose newest check failed, with their check history."""
        # The inner table is an alias so the newest-check subquery is never correlated with the
        # outer join's integrity_checks, and the join also states file_id = files.id: the result
        # is the same, but without it SQLAlchemy cannot see the join and warns of a cartesian
        # product.
        inner = aliased(IntegrityCheck)
        newest = (
            select(func.max(inner.id))
            .where(inner.file_id == File.id)
            .correlate(File)
            .scalar_subquery()
        )
        files = self.db.execute(
            select(
                File.id,
                File.file_uuid,
                File.original_filename,
                File.status,
                File.created_at,
                User.username,
            )
            .join(User, User.id == File.owner_id)
            .outerjoin(
                IntegrityCheck,
                and_(IntegrityCheck.file_id == File.id, IntegrityCheck.id == newest),
            )
            .where(
                File.status != "DELETED",
                (File.status == "CORRUPTED")
                | IntegrityCheck.result.in_(("MODIFIED", "MISSING", "ERROR")),
            )
            .order_by(File.updated_at.desc(), File.id.desc())
            .limit(limit)
        ).all()
        if not files:
            return []
        history: dict[int, list[tuple[str, datetime]]] = defaultdict(list)
        for file_id, result, at in self.db.execute(
            select(IntegrityCheck.file_id, IntegrityCheck.result, IntegrityCheck.created_at)
            .where(IntegrityCheck.file_id.in_([row[0] for row in files]))
            .order_by(IntegrityCheck.created_at.desc(), IntegrityCheck.id.desc())
        ):
            history[file_id].append((result, at))
        return [
            DamagedFileHistory(
                file_uuid=file_uuid,
                filename=filename,
                owner_username=username,
                status=status,
                uploaded_at=created_at,
                checks=tuple(history.get(file_id, ())),
            )
            for file_id, file_uuid, filename, status, created_at, username in files
        ]
