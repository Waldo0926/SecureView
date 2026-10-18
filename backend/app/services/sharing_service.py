from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db_retry import run_with_deadlock_retry
from app.core.time import to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.errors import (
    FileResourceNotFoundError,
    ShareStateConflictError,
    UserKeyNotFoundError,
)
from app.models.file_access_grant import FileAccessGrant
from app.models.file_key_wrapping import FileKeyWrapping
from app.repositories.sharing_repository import SharingRepository
from app.services.audit_log_service import AuditLogService
from app.services.crypto_service import CryptoService
from app.services.share_notification_service import ShareNotificationService


class SharingService:
    def __init__(
        self,
        *,
        db: Session,
        repository: SharingRepository | None = None,
        audit_service: AuditLogService | None = None,
        crypto_service: CryptoService | None = None,
        notifier: ShareNotificationService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.repository = repository or SharingRepository(db)
        self.audit = audit_service or AuditLogService(db, clock=clock)
        self.crypto = crypto_service or CryptoService()
        self.notifier = notifier
        self.clock = clock

    def _authorized_file(self, *, actor: ActorContext, file_id: UUID, capability: str):
        file = self.repository.lock_file(file_id)
        if file is None or file.status != "ACTIVE":
            raise FileResourceNotFoundError()
        grant = self.repository.lock_grant(file.id, actor.user_id)
        if (
            grant is None
            or grant.status != "ACTIVE"
            or not self.repository.has_active_wrapping(file.id, actor.user_id)
            or not bool(getattr(grant, capability))
        ):
            raise FileResourceNotFoundError()
        return file, grant

    def share(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        target_user_id: UUID,
        target_key_id: UUID,
        wrapped_file_key: bytes,
        can_download: bool,
        can_share: bool,
        context: RequestContext,
    ) -> tuple[bool, str]:
        created, status, newly_granted = run_with_deadlock_retry(
            self.db,
            lambda: self._attempt_share(
                actor=actor,
                file_id=file_id,
                target_user_id=target_user_id,
                target_key_id=target_key_id,
                wrapped_file_key=wrapped_file_key,
                can_download=can_download,
                can_share=can_share,
                context=context,
            ),
        )

        # After the commit, deliberately. The share has happened; a mail server that is
        # down must not turn a successful share into a reported failure, and must not roll
        # one back. The notifier swallows its own delivery errors for the same reason.
        # Only when the recipient did not already have the file: sharing it again to change
        # permissions or re-wrap the key mailed them a second "shared with you" for a file
        # they could already open.
        if self.notifier is not None and newly_granted:
            now = to_second_resolution_utc(self.clock())
            target_user = self.repository.get_user_by_uuid(target_user_id)
            actor_user = self.repository.get_user(actor.user_id)
            # Bound the notifier by what has already been sent today, so it can never eat
            # the allowance verification codes depend on.
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            self.notifier.sent_today = lambda: self.repository.count_shares_since(midnight)
            if target_user is not None:
                self.notifier.notify_shared(
                    recipient_email=target_user.email,
                    recipient_username=target_user.username,
                    sender_username=getattr(actor_user, "username", "Someone"),
                )

        return created, status

    def _attempt_share(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        target_user_id: UUID,
        target_key_id: UUID,
        wrapped_file_key: bytes,
        can_download: bool,
        can_share: bool,
        context: RequestContext,
    ) -> tuple[bool, str, bool]:
        """One full attempt, from re-reading the grant to the commit.

        Returns whether a grant row was created, the grant's status, and whether the
        recipient gained access with this call: a new grant, or a revoked one restored.

        A deadlock aborts the whole transaction (issue #139: sharing raced against a
        download can deadlock over the audit-chain-head lock and a `users` row), so a retry
        must redo every read here under a fresh lock, not reuse `file`/`grant` from a failed
        attempt.
        """
        try:
            file, actor_grant = self._authorized_file(
                actor=actor, file_id=file_id, capability="can_share"
            )
            if (can_download and not actor_grant.can_download) or (
                can_share and not actor_grant.can_share
            ):
                raise ShareStateConflictError(
                    "Shared permissions cannot exceed the acting account's permissions"
                )
            target = self.repository.lock_target_user_and_key(target_user_id, target_key_id)
            if target is None:
                raise UserKeyNotFoundError()
            target_user, target_key = target
            if target_user.id == file.owner_id:
                raise ShareStateConflictError("The canonical owner grant cannot be replaced")
            if target_user.id == actor.user_id:
                raise ShareStateConflictError("A file cannot be shared with the acting account")
            grant = self.repository.lock_grant(file.id, target_user.id)
            if grant is not None and not (
                actor_grant.can_manage or grant.granted_by == actor.user_id
            ):
                raise ShareStateConflictError(
                    "Only the original grantor or a file manager can update this grant"
                )
            try:
                self.crypto.validate_wrapped_file_key(
                    wrapped_file_key,
                    target_key.public_key_pem,
                )
            except (TypeError, ValueError) as exc:
                raise ShareStateConflictError("The wrapped file key is invalid") from exc

            now = to_second_resolution_utc(self.clock())
            created = grant is None
            newly_granted = grant is None or grant.status != "ACTIVE"
            if grant is None:
                grant = FileAccessGrant(
                    file_id=file.id,
                    user_id=target_user.id,
                    granted_by=actor.user_id,
                    can_download=can_download,
                    can_share=can_share,
                    can_revoke=False,
                    can_manage=False,
                    status="ACTIVE",
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                self.repository.add_grant(grant)
            else:
                grant.granted_by = actor.user_id
                grant.can_download = can_download
                grant.can_share = can_share
                grant.can_revoke = False
                grant.can_manage = False
                grant.status = "ACTIVE"
                grant.revoked_at = None
                grant.revision += 1
                grant.updated_at = now

            wrappings = self.repository.lock_user_wrappings(file.id, target_user.id)
            selected = None
            for wrapping in wrappings:
                if wrapping.user_key_id == target_key.id:
                    selected = wrapping
                elif wrapping.status == "ACTIVE":
                    wrapping.status = "REVOKED"
                    wrapping.revoked_at = now
                    wrapping.revision += 1
                    wrapping.updated_at = now
            if selected is None:
                selected = FileKeyWrapping(
                    file_id=file.id,
                    recipient_type="USER",
                    recipient_user_id=target_user.id,
                    user_key_id=target_key.id,
                    recovery_key_id=None,
                    wrapped_file_key=wrapped_file_key,
                    wrapping_algorithm="RSA-OAEP-SHA256",
                    status="ACTIVE",
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                self.repository.add_wrapping(selected)
            else:
                selected.wrapped_file_key = wrapped_file_key
                selected.status = "ACTIVE"
                selected.revoked_at = None
                selected.revision += 1
                selected.updated_at = now

            self.audit.append(
                action="FILE_SHARED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=target_user.id,
                resource_type="SHARE",
                resource_id=str(file_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "target_user_id": str(target_user_id),
                    "target_key_id": str(target_key_id),
                    "can_download": can_download,
                    "can_share": can_share,
                },
            )
            self.db.commit()
            return created, "ACTIVE", newly_granted
        except Exception:
            self.db.rollback()
            raise

    def list_shared_users(self, *, actor: ActorContext, file_id: UUID):
        file, _grant = self._authorized_file(
            actor=actor,
            file_id=file_id,
            capability="can_share",
        )
        return file, self.repository.list_shared_users(file.id)

    def revoke(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        target_user_id: UUID,
        context: RequestContext,
    ) -> bool:
        try:
            file, _actor_grant = self._authorized_file(
                actor=actor,
                file_id=file_id,
                capability="can_revoke",
            )
            target_user = self.repository.get_user_by_uuid(target_user_id)
            if target_user is None:
                raise FileResourceNotFoundError()
            if target_user.id == file.owner_id:
                raise ShareStateConflictError("The canonical owner cannot be revoked")

            now = to_second_resolution_utc(self.clock())
            changed = False
            grant = self.repository.lock_grant(file.id, target_user.id)
            if grant is not None and grant.status == "ACTIVE":
                grant.status = "REVOKED"
                grant.revoked_at = now
                grant.revision += 1
                grant.updated_at = now
                changed = True
            for wrapping in self.repository.lock_user_wrappings(file.id, target_user.id):
                if wrapping.status == "ACTIVE":
                    wrapping.status = "REVOKED"
                    wrapping.revoked_at = now
                    wrapping.revision += 1
                    wrapping.updated_at = now
                    changed = True

            self.audit.append(
                action="FILE_ACCESS_REVOKED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=target_user.id,
                resource_type="SHARE",
                resource_id=str(file_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"target_user_id": str(target_user_id), "changed": changed},
            )
            self.db.commit()
            return changed
        except Exception:
            self.db.rollback()
            raise
