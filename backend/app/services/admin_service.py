from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import PasswordOperationCapacityError, hash_password, password_policy_error
from app.core.time import to_api_utc, to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    AuthenticationRateLimitedError,
    AuthorizationError,
    ConflictError,
    LastAdministratorError,
    ResourceNotFoundError,
)
from app.repositories.admin_repository import AdminRepository
from app.repositories.auth_repository import AuthRepository
from app.schemas.admin_schema import (
    AdminAuditEventOut,
    AdminAuditStats,
    AdminDamagedFileOut,
    AdminFileStats,
    AdminIntegrityCoverage,
    AdminIntegrityReportOut,
    AdminIntegrityScanOut,
    AdminIntegrityStats,
    AdminRecoveryStats,
    AdminShareStats,
    AdminStatsOut,
    AdminUserStats,
)
from app.services.account_notice_service import AccountNoticeService
from app.services.audit_log_service import AuditLogService
from app.services.integrity_service import IntegrityService

# No 0/O, 1/l/I: the temporary password is read out or copied by hand.
_TEMPORARY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def temporary_password(*, context_values: Iterable[str] = ()) -> str:
    """Four groups of four, e.g. `Kx7m-Q2pa-9Wvt-H3nc`: about 95 bits, and it passes the policy."""
    values = tuple(context_values)
    while True:
        groups = ["".join(secrets.choice(_TEMPORARY_ALPHABET) for _ in range(4)) for _ in range(4)]
        candidate = "-".join(groups)
        if password_policy_error(candidate, context_values=values) is None:
            return candidate


class AdminService:
    def __init__(
        self,
        *,
        db: Session,
        repository: AdminRepository | None = None,
        auth_repository: AuthRepository | None = None,
        audit_service: AuditLogService | None = None,
        integrity_service: IntegrityService | None = None,
        notices: AccountNoticeService | None = None,
        hash_password: Callable[[str], str] = hash_password,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.repository = repository or AdminRepository(db)
        self.auth_repository = auth_repository or AuthRepository(db)
        self.audit = audit_service or AuditLogService(db, clock=clock)
        self.integrity = integrity_service
        self.notices = notices
        self.hash_password = hash_password
        self.clock = clock

    @staticmethod
    def _require_admin(actor: ActorContext) -> None:
        if actor.role is not SystemRole.ADMIN:
            raise AuthorizationError()

    def platform_stats(self, *, actor: ActorContext) -> AdminStatsOut:
        """Summarise the platform with counts only, for the administrator dashboard."""
        self._require_admin(actor)
        now = self.clock()
        since_day = to_second_resolution_utc(now - timedelta(hours=24))
        since_week = to_second_resolution_utc(now - timedelta(days=7))
        repo = self.repository

        users = repo.user_counts_by_status()
        files = repo.file_counts_by_status()
        original_bytes, stored_bytes = repo.stored_totals()
        active_shares, files_shared = repo.share_counts()
        checks, failed_checks = repo.integrity_check_counts_since(since_day)
        events_total, events_day, failures_day = repo.audit_counts(since_day)

        existing_files = files.get("ACTIVE", 0) + files.get("CORRUPTED", 0)
        return AdminStatsOut(
            generated_at=to_api_utc(now),
            users=AdminUserStats(
                total=sum(users.values()),
                active=users.get(UserStatus.ACTIVE.value, 0),
                disabled=users.get(UserStatus.DISABLED.value, 0),
                deleted=users.get(UserStatus.DELETED.value, 0),
                administrators=repo.count_administrators(),
                created_last_7_days=repo.count_users_created_since(since_week),
                signed_in_last_24_hours=repo.count_users_signed_in_since(since_day),
            ),
            files=AdminFileStats(
                total=existing_files,
                active=files.get("ACTIVE", 0),
                corrupted=files.get("CORRUPTED", 0),
                deleted=files.get("DELETED", 0),
                uploaded_last_24_hours=repo.count_files_uploaded_since(since_day),
                original_bytes=original_bytes,
                stored_bytes=stored_bytes,
                by_algorithm=repo.file_counts_by_algorithm(),
            ),
            shares=AdminShareStats(active_shares=active_shares, files_shared=files_shared),
            integrity=AdminIntegrityStats(
                checks_last_24_hours=checks, failed_checks_last_24_hours=failed_checks
            ),
            recovery=AdminRecoveryStats(pending_requests=repo.count_pending_recovery_requests()),
            audit=AdminAuditStats(
                events_total=events_total,
                events_last_24_hours=events_day,
                failures_last_24_hours=failures_day,
                recent_failures=[
                    AdminAuditEventOut(
                        action=action,
                        result=result,
                        created_at=to_api_utc(created_at),
                        actor_username=username,
                    )
                    for action, result, created_at, username in repo.recent_audit_failures(limit=5)
                ],
            ),
        )

    def integrity_report(self, *, actor: ActorContext, limit: int) -> AdminIntegrityReportOut:
        """Which files are damaged and how much of the store has been checked at all."""
        self._require_admin(actor)
        now = self.clock()
        candidates, never, recent, last_sweep = self.repository.integrity_coverage(
            to_second_resolution_utc(now - timedelta(hours=24))
        )
        rows = self.repository.damaged_files(limit=limit + 1)
        return AdminIntegrityReportOut(
            generated_at=to_api_utc(now),
            coverage=AdminIntegrityCoverage(
                candidates=candidates,
                never_checked=never,
                checked_last_24_hours=recent,
                last_sweep_at=to_api_utc(last_sweep),
            ),
            damaged=[
                AdminDamagedFileOut(
                    file_id=UUID(row.file_uuid),
                    owner_username=row.owner_username,
                    original_filename=row.original_filename,
                    status=row.status,
                    last_result=row.last_result,
                    last_message=row.last_message,
                    last_checked_at=to_api_utc(row.last_checked_at),
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    def scan_integrity(
        self,
        *,
        actor: ActorContext,
        context: RequestContext,
        limit: int,
        budget_seconds: float,
    ) -> AdminIntegrityScanOut:
        """Verify a bounded batch of stored objects now, least recently checked first."""
        self._require_admin(actor)
        if self.integrity is None:  # pragma: no cover - wiring invariant
            raise RuntimeError("AdminService was built without an IntegrityService")
        summary = self.integrity.sweep(
            actor_user_id=actor.user_id,
            context=context,
            limit=limit,
            budget_seconds=budget_seconds,
        )
        return AdminIntegrityScanOut(
            scanned=summary.scanned,
            valid=summary.valid,
            damaged=summary.damaged,
            candidates=summary.candidates,
            stopped_early=summary.stopped_early,
            damaged_file_ids=[UUID(value) for value in summary.damaged_file_ids],
        )

    def list_users(
        self, *, actor: ActorContext, limit: int, offset: int, status: str | None = None
    ):
        self._require_admin(actor)
        return self.repository.list_users(limit=limit + 1, offset=offset, status=status)

    def user_detail(self, *, actor: ActorContext, user_id: UUID):
        self._require_admin(actor)
        user = self.repository.get_user_by_uuid(user_id)
        if user is None:
            raise ResourceNotFoundError()
        now = to_second_resolution_utc(self.clock())
        return user, self.repository.user_activity(user.id, now=now)

    def reset_user_password(
        self,
        *,
        actor: ActorContext,
        user_id: UUID,
        context: RequestContext,
    ) -> tuple[object, str, int, bool]:
        """Give an account a new, random login password and sign it out everywhere.

        The administrator sees the temporary password once, in the response; only its hash is
        stored. It changes the login password and nothing else: the encryption passphrase never
        reaches the server, so every file stays exactly as openable as before. An administrator
        cannot use this on themselves or on another administrator, and the holder is emailed.
        """
        self._require_admin(actor)
        if user_id == actor.user_public_id:
            raise ConflictError("Change your own password in Settings")
        try:
            user = self.repository.lock_user_by_uuid(user_id)
            if user is None or user.status is UserStatus.DELETED:
                raise ResourceNotFoundError()
            if user.role is SystemRole.ADMIN:
                raise ConflictError("Another administrator's password cannot be reset here")
            temporary = temporary_password(context_values=(user.username, user.email))
            now = to_second_resolution_utc(self.clock())
            user.password_hash = self.hash_password(temporary)
            user.password_changed_at = now
            user.updated_at = now
            # The temporary password has been seen by the administrator and travels by
            # hand, so the holder is sent to choose their own at the next sign-in. Until
            # then `get_current_actor` refuses every route except the few needed to do it.
            user.must_change_password = True
            revoked = self.auth_repository.revoke_all_session_families(
                user.id, now=now, reason="admin_password_reset"
            )
            self.audit.append(
                action="ADMIN_PASSWORD_RESET",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=user.id,
                resource_type="USER",
                resource_id=str(user_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"revoked_sessions": revoked},
            )
            self.db.commit()
        except PasswordOperationCapacityError as exc:
            # No memory budget for another hash right now: the same brief 429 that sign-in
            # gives, rather than a 500. Nothing was changed.
            self.db.rollback()
            raise AuthenticationRateLimitedError(retry_after_seconds=1) from exc
        except Exception:
            self.db.rollback()
            raise
        notice_sent = (
            self.notices.notify_admin_password_reset(email=user.email, username=user.username)
            if self.notices is not None
            else False
        )
        return user, temporary, revoked, notice_sent

    def list_files(
        self, *, actor: ActorContext, limit: int, offset: int, status: str | None = None
    ):
        self._require_admin(actor)
        return self.repository.list_files(limit=limit + 1, offset=offset, status=status)

    def set_user_enabled(
        self,
        *,
        actor: ActorContext,
        user_id: UUID,
        enabled: bool,
        context: RequestContext,
    ) -> tuple[object, bool, int]:
        self._require_admin(actor)
        if user_id == actor.user_public_id:
            raise ConflictError("An administrator cannot change their own account status")
        try:
            administrators = []
            if not enabled:
                # Taken before the target row and in id order, the same order account
                # deletion takes them in. Two administrators disabling each other at once
                # would otherwise each see the other still active and leave none.
                administrators = self.auth_repository.lock_administrators()
            user = self.repository.lock_user_by_uuid(user_id)
            if user is None or user.status is UserStatus.DELETED:
                raise ResourceNotFoundError()
            if (
                not enabled
                and user.role is SystemRole.ADMIN
                and not any(
                    other.id != user.id and other.status is UserStatus.ACTIVE
                    for other in administrators
                )
            ):
                raise LastAdministratorError()
            desired = UserStatus.ACTIVE if enabled else UserStatus.DISABLED
            changed = user.status is not desired
            revoked_sessions = 0
            now = to_second_resolution_utc(self.clock())
            if changed:
                user.status = desired
                user.updated_at = now
                if not enabled:
                    revoked_sessions = self.auth_repository.revoke_all_session_families(
                        user.id,
                        now=now,
                        reason="account_disabled",
                    )
            self.audit.append(
                action="USER_ENABLED" if enabled else "USER_DISABLED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=user.id,
                resource_type="USER",
                resource_id=str(user_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"changed": changed, "revoked_sessions": revoked_sessions},
            )
            self.db.commit()
            return user, changed, revoked_sessions
        except Exception:
            self.db.rollback()
            raise
