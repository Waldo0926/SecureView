from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.security import PasswordManager, PasswordOperationCapacityError
from app.core.time import to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    AuthenticationError,
    AuthenticationRateLimitedError,
    InvalidCurrentPasswordError,
    LastAdministratorError,
)
from app.repositories.auth_repository import AuthRepository
from app.repositories.file_repository import FileRepository
from app.services.audit_log_service import AuditLogService
from app.services.auth_service import AuthService
from app.services.avatar_storage_service import AvatarStorageService
from app.services.file_storage_service import FileStorageService, StorageObjectError

logger = logging.getLogger(__name__)


class AccountDeletionResult:
    """What closing the account actually removed, for the response and the audit entry."""

    def __init__(self, *, files_deleted: int, sessions_revoked: int) -> None:
        self.files_deleted = files_deleted
        self.sessions_revoked = sessions_revoked


class AccountDeletionService:
    """Close an account and destroy what it owns.

    This exists because a forgotten encryption passphrase is unrecoverable by design. The
    offline recovery workflow cannot recover one, and `POST /keys/me/rewrap` cannot set a new
    one without the account master key -- which is exactly what the forgotten passphrase
    protects. So the honest remaining path for someone locked out of their own files is to
    start again, and that needs to be something they can do themselves rather than something
    they ask a teammate to do in the database.

    Deletion is deliberately not reversible and does not try to be. What it is careful about
    is order: the database commit lands before any ciphertext is unlinked, matching
    `FileService.delete`, so a process that dies midway leaves rows marked DELETED with their
    objects still present -- recoverable by the reconcile job -- rather than live rows whose
    ciphertext has already gone.
    """

    def __init__(
        self,
        *,
        db: Session,
        passwords: PasswordManager,
        storage: FileStorageService,
        reauthentication: AuthService,
        avatar_storage: AvatarStorageService | None = None,
        auth_repository: AuthRepository | None = None,
        file_repository: FileRepository | None = None,
        audit_service: AuditLogService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.passwords = passwords
        self.storage = storage
        # The password check here shares the change-password throttle buckets, so a wrong
        # guess costs the same wherever it is made. Required, not optional: a wiring that
        # forgot it would quietly leave this endpoint open to unlimited guessing.
        self.reauthentication = reauthentication
        self.avatar_storage = avatar_storage
        self.auth = auth_repository or AuthRepository(db)
        self.files = file_repository or FileRepository(db)
        self.audit = audit_service or AuditLogService(db)
        self._clock = clock

    def delete_account(
        self,
        *,
        actor: ActorContext,
        password: str,
        context: RequestContext,
    ) -> AccountDeletionResult:
        """Verify the password, then close the account.

        The password is required even though the caller already holds a valid session. This
        is the one action in the application that cannot be undone, and a session left open
        on an unattended machine should not be enough to trigger it.
        """
        # Naive UTC to the second, the form every column written here stores. The throttle
        # rows in particular are compared with it, and an aware value raised a TypeError (a
        # 500). The audit row takes its own time from AuditLogService.
        now = to_second_resolution_utc(self._clock())
        object_keys: list[str] = []
        avatar_key: str | None = None

        try:
            # Read without a lock first: the throttle check commits, which would release
            # a row lock taken before it. The locked read comes after.
            account = self.auth.get_user(actor.user_id)
            if account is None or account.status is not UserStatus.ACTIVE:
                raise AuthenticationError()
            buckets = self.reauthentication.begin_reauthentication(
                username=account.username,
                context=context,
                now=now,
            )

            administrators = []
            if account.role is SystemRole.ADMIN:
                # Before the account's own row, in the order an administrator disable takes
                # them, so two administrators closing their accounts at once cannot each
                # count the other as the one who stays.
                administrators = self.auth.lock_administrators()
            user = self.auth.lock_user(actor.user_id)
            if user is None or user.status is not UserStatus.ACTIVE:
                raise AuthenticationError()
            # Nothing in the application can appoint an administrator, so closing the last
            # active one would leave the admin console out of reach without a database edit.
            if user.role is SystemRole.ADMIN and not any(
                other.id != user.id and other.status is UserStatus.ACTIVE
                for other in administrators
            ):
                raise LastAdministratorError()

            if not self.passwords.verify(password, user.password_hash):
                # Committed on its own, so the count and the audit row outlive the
                # rollback below.
                self.reauthentication.record_reauthentication_failure(
                    user=user,
                    buckets=buckets,
                    context=context,
                    now=now,
                    action="ACCOUNT_DELETION_PASSWORD_FAILED",
                    description="Account deletion password verification failed",
                )
                raise InvalidCurrentPasswordError()
            self.reauthentication.clear_reauthentication_throttle(buckets=buckets, now=now)

            avatar_key = user.avatar_object_key
            user.avatar_object_key = None
            user.avatar_content_type = None
            user.avatar_sha256 = None
            user.avatar_bytes = None
            user.avatar_updated_at = None

            owned = self.files.lock_owned_files(user.id)
            for file_record in owned:
                object_keys.append(file_record.storage_object_key)
                file_record.status = "DELETED"
                file_record.deleted_at = now
                file_record.updated_at = now
                if hasattr(file_record, "revision"):
                    file_record.revision += 1
                # Revoking the grants matters as much as marking the file: a share handed to
                # someone else must not outlive the account that granted it.
                self.files.revoke_file_access_rows(file_record.id, revoked_at=now)

            sessions_revoked = self.auth.revoke_all_session_families(
                user.id,
                now=now,
                reason="account_deleted",
            )

            # Recorded against the still-real username, before it is released.
            self.audit.append(
                action="ACCOUNT_DELETED",
                result="SUCCESS",
                actor_user_id=user.id,
                target_user_id=user.id,
                resource_type="USER",
                resource_id=str(actor.user_public_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "files_deleted": len(owned),
                    "sessions_revoked": sessions_revoked,
                    "username": user.username,
                },
            )

            user.status = UserStatus.DELETED
            self.auth.release_identifiers(user, tombstone=uuid4().hex)

            self.db.commit()
        except PasswordOperationCapacityError as exc:
            # No memory budget for another hash right now. Like AuthService, this is a
            # brief 429 rather than a 500, and nothing is recorded as a wrong guess.
            self.db.rollback()
            raise AuthenticationRateLimitedError(retry_after_seconds=1) from exc
        except Exception:
            self.db.rollback()
            raise

        # After the durable commit, for the same reason FileService.delete does it here.
        # The account is already closed by now, so a failure to unlink one object must not
        # turn the answer into an error: the caller would think nothing happened. Each
        # failure is logged and the rest are still removed. What is left behind belongs to
        # rows marked DELETED, which the reconcile job finds and removes.
        for object_key in object_keys:
            try:
                self.storage.delete_object(object_key)
            except (StorageObjectError, OSError, ValueError) as exc:
                # The type only: an OSError message carries the host path of the object.
                logger.warning(
                    "Could not remove a deleted account's file object: %s", type(exc).__name__
                )

        if self.avatar_storage is not None and avatar_key:
            try:
                self.avatar_storage.delete_sync(avatar_key)
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Could not remove a deleted account's avatar: %s", type(exc).__name__
                )

        return AccountDeletionResult(
            files_deleted=len(object_keys),
            sessions_revoked=sessions_revoked,
        )
