from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    FileResourceNotFoundError,
    InputError,
    RecoveryRequestNotFoundError,
    RecoveryStateConflictError,
    ResourceNotFoundError,
    UserKeyNotFoundError,
)
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.recovery_key import RecoveryKey
from app.models.recovery_request import RecoveryRequest
from app.repositories.recovery_repository import (
    RecoveryExecutionRecord,
    RecoveryRepository,
    RecoveryRequestRecord,
)
from app.services.audit_log_service import AuditLogService
from app.services.crypto_service import CryptoService

_REVIEWER_ROLES = frozenset({SystemRole.ADMIN, SystemRole.RECOVERY_OFFICER})


class RecoveryService:
    """Coordinates client/offline recovery without accepting recovery private keys."""

    def __init__(
        self,
        *,
        db: Session,
        repository: RecoveryRepository | None = None,
        audit_service: AuditLogService | None = None,
        crypto_service: CryptoService | None = None,
        clock: Callable[[], datetime] = utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
        request_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        if request_ttl <= timedelta(0):
            raise ValueError("request_ttl must be positive")
        self.db = db
        self.repository = repository or RecoveryRepository(db)
        self.audit = audit_service or AuditLogService(db, clock=clock)
        self.crypto = crypto_service or CryptoService()
        self.clock = clock
        self.uuid_factory = uuid_factory
        self.request_ttl = request_ttl

    def _now(self) -> datetime:
        return to_second_resolution_utc(self.clock())

    @staticmethod
    def _require_reviewer(actor: ActorContext) -> None:
        if actor.role not in _REVIEWER_ROLES:
            raise AuthorizationError()

    @staticmethod
    def _require_admin(actor: ActorContext) -> None:
        if actor.role is not SystemRole.ADMIN:
            raise AuthorizationError()

    def _record(self, request_id: UUID) -> RecoveryRequestRecord:
        record = self.repository.get_request_record(request_id)
        if record is None:  # pragma: no cover - transaction invariant
            raise RuntimeError("Committed recovery request could not be reloaded")
        return record

    def get_public_key(self, *, actor: ActorContext) -> RecoveryKey:
        del actor  # Authentication is enforced at the route boundary.
        key = self.repository.get_active_recovery_key()
        if key is None:
            raise ResourceNotFoundError("No active recovery public key is configured")
        return key

    def register_public_key(
        self,
        *,
        actor: ActorContext,
        key_id: UUID,
        public_key_pem: str,
        algorithm: str,
        context: RequestContext,
    ) -> tuple[RecoveryKey, bool, int]:
        self._require_admin(actor)
        if algorithm != "RSA-OAEP-SHA256":
            raise InputError("The recovery key algorithm is not supported")
        try:
            public_key = self.crypto.load_rsa_public_key(public_key_pem)
        except (TypeError, ValueError) as exc:
            raise InputError("The recovery public key is invalid") from exc
        if public_key.key_size not in {2048, 3072, 4096}:
            raise InputError("The recovery public key size is not supported")
        fingerprint = self.crypto.public_key_fingerprint(public_key_pem)

        try:
            now = self._now()
            existing = self.repository.get_recovery_key_by_uuid(key_id, for_update=True)
            fingerprint_owner = self.repository.get_recovery_key_by_fingerprint(fingerprint)
            if existing is not None and existing.fingerprint != fingerprint:
                raise ConflictError("key_id has already been used for another recovery key")
            if fingerprint_owner is not None and (
                existing is None or fingerprint_owner.id != existing.id
            ):
                raise ConflictError("The recovery public key is already registered")
            if existing is not None and existing.status != "ACTIVE":
                raise ConflictError("A revoked recovery key cannot be reactivated")

            active_keys = self.repository.lock_active_recovery_keys()
            rotated = 0
            for active_key in active_keys:
                if existing is None or active_key.id != existing.id:
                    active_key.status = "REVOKED"
                    active_key.revoked_at = now
                    rotated += 1

            created = existing is None
            if existing is None:
                existing = RecoveryKey(
                    key_uuid=str(key_id),
                    public_key_pem=public_key_pem,
                    algorithm=algorithm,
                    key_size_bits=public_key.key_size,
                    fingerprint=fingerprint,
                    status="ACTIVE",
                    created_at=now,
                    revoked_at=None,
                )
                self.repository.add_recovery_key(existing)
                self.repository.flush()

            changed = created or rotated > 0
            if changed:
                self.audit.append(
                    action=("RECOVERY_KEY_REGISTERED" if rotated == 0 else "RECOVERY_KEY_ROTATED"),
                    result="SUCCESS",
                    actor_user_id=actor.user_id,
                    resource_type="RECOVERY",
                    resource_id=str(key_id),
                    context_ip_address=context.ip_address,
                    context_user_agent=context.user_agent,
                    metadata={"rotated_keys": rotated, "key_size_bits": public_key.key_size},
                )
                self.db.commit()
            return existing, created, rotated
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("The recovery public key is already registered") from exc
        except Exception:
            self.db.rollback()
            raise

    def revoke_public_key(
        self,
        *,
        actor: ActorContext,
        key_id: UUID,
        context: RequestContext,
    ) -> tuple[RecoveryKey, bool]:
        self._require_admin(actor)
        try:
            key = self.repository.get_recovery_key_by_uuid(key_id, for_update=True)
            if key is None:
                raise ResourceNotFoundError("The recovery public key was not found")
            if key.status == "REVOKED":
                return key, False
            key.status = "REVOKED"
            key.revoked_at = self._now()
            self.audit.append(
                action="RECOVERY_KEY_REVOKED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                resource_type="RECOVERY",
                resource_id=str(key_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
            )
            self.db.commit()
            return key, True
        except Exception:
            self.db.rollback()
            raise

    def create_request(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        reason: str,
        target_key_id: UUID,
        context: RequestContext,
    ) -> RecoveryRequestRecord:
        try:
            now = self._now()
            file = self.repository.lock_file(file_id)
            if file is None or file.status == "DELETED":
                raise FileResourceNotFoundError()
            grant = self.repository.lock_grant(file.id, actor.user_id)
            if grant is None or grant.status != "ACTIVE" or not grant.can_download:
                raise FileResourceNotFoundError()
            if file.status != "ACTIVE":
                # CORRUPTED: the integrity sweep found the stored ciphertext changed. A recovery
                # request re-seals the file key to the requester's account key; it cannot put
                # the bytes back, and answering "not found" here sent people looking for a
                # file they could see in their list. The requester holds an active grant, so
                # the status is nothing they do not already see on the file.
                raise RecoveryStateConflictError(
                    "This file's stored copy failed its integrity check. Request recovery "
                    "re-seals the file key to your account key and cannot repair changed "
                    "content; an administrator restores the file from backup, and it then "
                    "downloads as before."
                )
            target_key = self.repository.lock_active_target_key(actor.user_id, target_key_id)
            if target_key is None:
                raise UserKeyNotFoundError()
            if self.repository.lock_active_user_wrapping(file.id, actor.user_id) is None:
                raise FileResourceNotFoundError()
            if self.repository.lock_active_recovery_wrapping(file.id) is None:
                raise RecoveryStateConflictError(
                    "The file does not have an active recovery-key wrapping"
                )
            if (
                self.repository.lock_pending_request(
                    file_id=file.id,
                    requested_by=actor.user_id,
                    now=now,
                )
                is not None
            ):
                raise RecoveryStateConflictError(
                    "An unexpired recovery request is already pending for this file"
                )

            request_id = self.uuid_factory()
            request = RecoveryRequest(
                request_uuid=str(request_id),
                file_id=file.id,
                requested_by=actor.user_id,
                approved_by=None,
                executed_by=None,
                target_user_key_id=target_key.id,
                result_wrapping_id=None,
                reason=reason,
                rejection_reason=None,
                status="PENDING",
                created_at=now,
                updated_at=now,
                expires_at=now + self.request_ttl,
                approved_at=None,
                rejected_at=None,
                executed_at=None,
                cancelled_at=None,
                revision=1,
            )
            self.repository.add_request(request)
            self.audit.append(
                action="RECOVERY_REQUEST_CREATED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_type="RECOVERY",
                resource_id=str(file.file_uuid),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "request_id": str(request_id),
                    "target_key_id": str(target_key_id),
                },
            )
            self.db.commit()
            return self._record(request_id)
        except Exception:
            self.db.rollback()
            raise

    def approve_request(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
        context: RequestContext,
    ) -> RecoveryRequestRecord:
        self._require_reviewer(actor)
        return self._review_request(
            actor=actor,
            request_id=request_id,
            approve=True,
            rejection_reason=None,
            context=context,
        )

    def reject_request(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
        rejection_reason: str,
        context: RequestContext,
    ) -> RecoveryRequestRecord:
        self._require_reviewer(actor)
        return self._review_request(
            actor=actor,
            request_id=request_id,
            approve=False,
            rejection_reason=rejection_reason,
            context=context,
        )

    def _review_request(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
        approve: bool,
        rejection_reason: str | None,
        context: RequestContext,
    ) -> RecoveryRequestRecord:
        try:
            locator = self.repository.get_request_locator(request_id)
            if locator is None:
                raise RecoveryRequestNotFoundError()
            file = self.repository.lock_file_by_id(locator.file_id)
            if file is None:  # pragma: no cover - protected by the recovery-request FK
                raise RecoveryRequestNotFoundError()
            request = self.repository.lock_request(request_id)
            if (
                request is None
                or request.file_id != locator.file_id
                or request.requested_by != locator.requested_by
                or request.target_user_key_id != locator.target_user_key_id
            ):
                raise RecoveryRequestNotFoundError()
            if request.requested_by == actor.user_id:
                raise AuthorizationError("A recovery request cannot be self-reviewed")
            now = self._now()
            if request.status != "PENDING":
                raise RecoveryStateConflictError()
            if request.expires_at <= now:
                raise RecoveryStateConflictError("The recovery request has expired")

            request.approved_by = actor.user_id
            request.updated_at = now
            request.revision += 1
            if approve:
                request.status = "APPROVED"
                request.approved_at = now
                action = "RECOVERY_REQUEST_APPROVED"
            else:
                request.status = "REJECTED"
                request.rejection_reason = rejection_reason
                request.rejected_at = now
                action = "RECOVERY_REQUEST_REJECTED"

            self.audit.append(
                action=action,
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=request.requested_by,
                resource_type="RECOVERY",
                resource_id=str(file.file_uuid),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"request_id": str(request_id)},
            )
            self.db.commit()
            return self._record(request_id)
        except Exception:
            self.db.rollback()
            raise

    def cancel_request(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
        context: RequestContext,
    ) -> tuple[RecoveryRequestRecord, bool]:
        try:
            locator = self.repository.get_request_locator(request_id)
            if locator is None:
                raise RecoveryRequestNotFoundError()
            file = self.repository.lock_file_by_id(locator.file_id)
            if file is None:  # pragma: no cover - protected by the recovery-request FK
                raise RecoveryRequestNotFoundError()
            request = self.repository.lock_request(request_id)
            if (
                request is None
                or request.file_id != locator.file_id
                or request.requested_by != locator.requested_by
                or request.target_user_key_id != locator.target_user_key_id
            ):
                raise RecoveryRequestNotFoundError()
            if request.requested_by != actor.user_id:
                raise RecoveryRequestNotFoundError()
            if request.status == "CANCELLED":
                return self._record(request_id), False
            if request.status not in {"PENDING", "APPROVED"}:
                raise RecoveryStateConflictError()

            now = self._now()
            request.status = "CANCELLED"
            request.approved_by = None
            request.approved_at = None
            request.cancelled_at = now
            request.updated_at = now
            request.revision += 1
            self.audit.append(
                action="RECOVERY_REQUEST_CANCELLED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_type="RECOVERY",
                resource_id=str(file.file_uuid),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"request_id": str(request_id)},
            )
            self.db.commit()
            return self._record(request_id), True
        except Exception:
            self.db.rollback()
            raise

    def execute_request(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
        wrapped_file_key: bytes,
        recovery_key_id: UUID,
        target_key_id: UUID,
        context: RequestContext,
    ) -> tuple[RecoveryRequestRecord, bool]:
        self._require_reviewer(actor)
        try:
            locator = self.repository.get_request_locator(request_id)
            if locator is None:
                raise RecoveryRequestNotFoundError()
            file = self.repository.lock_file_by_id(locator.file_id)
            if file is None or file.status != "ACTIVE":
                raise FileResourceNotFoundError()

            grant = self.repository.lock_grant(file.id, locator.requested_by)
            if grant is None or grant.status != "ACTIVE" or not grant.can_download:
                raise RecoveryStateConflictError("The requester's file access is no longer active")
            target_key = self.repository.lock_active_target_key(
                locator.requested_by,
                target_key_id,
            )
            if target_key is None:
                raise UserKeyNotFoundError()
            if locator.target_user_key_id != target_key.id:
                raise RecoveryStateConflictError(
                    "target_key_id does not match the approved recovery request"
                )
            if self.repository.lock_active_user_wrapping(file.id, locator.requested_by) is None:
                raise RecoveryStateConflictError(
                    "The requester's file-key wrapping is no longer active"
                )
            user_wrappings = self.repository.lock_user_wrappings(
                file.id,
                locator.requested_by,
            )
            source = self.repository.lock_recovery_source(
                file_id=file.id,
                recovery_key_id=recovery_key_id,
            )
            if source is None:
                raise RecoveryStateConflictError(
                    "recovery_key_id does not match an active file recovery wrapping"
                )
            recovery_wrapping, recovery_key = source
            request = self.repository.lock_request(request_id)
            if (
                request is None
                or request.file_id != locator.file_id
                or request.requested_by != locator.requested_by
                or request.target_user_key_id != locator.target_user_key_id
            ):
                raise RecoveryRequestNotFoundError()
            try:
                self.crypto.validate_wrapped_file_key(
                    recovery_wrapping.wrapped_file_key,
                    recovery_key.public_key_pem,
                )
                self.crypto.validate_wrapped_file_key(
                    wrapped_file_key,
                    target_key.public_key_pem,
                )
            except (TypeError, ValueError) as exc:
                raise RecoveryStateConflictError("The wrapped file key is invalid") from exc

            if request.status == "EXECUTED":
                result = next(
                    (
                        wrapping
                        for wrapping in user_wrappings
                        if wrapping.id == request.result_wrapping_id
                    ),
                    None,
                )
                if (
                    result is not None
                    and result.status == "ACTIVE"
                    and result.recipient_type == "USER"
                    and result.recipient_user_id == request.requested_by
                    and result.user_key_id == target_key.id
                    and result.wrapped_file_key == wrapped_file_key
                ):
                    return self._record(request_id), False
                raise RecoveryStateConflictError(
                    "The recovery request was executed with a different result"
                )

            now = self._now()
            if request.status != "APPROVED":
                raise RecoveryStateConflictError()
            if request.expires_at <= now:
                raise RecoveryStateConflictError("The recovery request has expired")

            selected: FileKeyWrapping | None = None
            for wrapping in user_wrappings:
                if wrapping.user_key_id == target_key.id:
                    selected = wrapping
                elif wrapping.status == "ACTIVE":
                    wrapping.status = "REVOKED"
                    wrapping.revoked_at = now
                    wrapping.updated_at = now
                    wrapping.revision += 1
            if selected is None:
                selected = FileKeyWrapping(
                    file_id=file.id,
                    recipient_type="USER",
                    recipient_user_id=request.requested_by,
                    user_key_id=target_key.id,
                    recovery_key_id=None,
                    wrapped_file_key=wrapped_file_key,
                    wrapping_algorithm="RSA-OAEP-SHA256",
                    status="ACTIVE",
                    created_at=now,
                    updated_at=now,
                    revoked_at=None,
                    revision=1,
                )
                self.repository.add_wrapping(selected)
                self.repository.flush()
            else:
                selected.wrapped_file_key = wrapped_file_key
                selected.wrapping_algorithm = "RSA-OAEP-SHA256"
                selected.status = "ACTIVE"
                selected.revoked_at = None
                selected.updated_at = now
                selected.revision += 1

            request.status = "EXECUTED"
            request.executed_by = actor.user_id
            request.result_wrapping_id = selected.id
            request.executed_at = now
            request.updated_at = now
            request.revision += 1
            self.audit.append(
                action="RECOVERY_REQUEST_EXECUTED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=request.requested_by,
                resource_type="RECOVERY",
                resource_id=str(file.file_uuid),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "request_id": str(request_id),
                    "target_key_id": str(target_key_id),
                    "recovery_key_id": str(recovery_key_id),
                },
            )
            self.db.commit()
            return self._record(request_id), True
        except Exception:
            self.db.rollback()
            raise

    def get_execution_package(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
    ) -> RecoveryExecutionRecord:
        self._require_reviewer(actor)
        record = self.repository.get_execution_record(request_id)
        if record is None:
            raise RecoveryRequestNotFoundError()
        if record.request.status != "APPROVED":
            raise RecoveryStateConflictError()
        if record.request.expires_at <= self._now():
            raise RecoveryStateConflictError("The recovery request has expired")
        if record.file.status != "ACTIVE" or record.target_key.status != "ACTIVE":
            raise RecoveryStateConflictError("The recovery request no longer has an active target")
        if not self.repository.has_active_download_entitlement(
            record.file.id,
            record.request.requested_by,
        ):
            raise RecoveryStateConflictError("The requester's file access is no longer active")
        try:
            self.crypto.validate_wrapped_file_key(
                record.source_wrapping.wrapped_file_key,
                record.recovery_key.public_key_pem,
            )
        except (TypeError, ValueError) as exc:
            raise RecoveryStateConflictError("The file recovery wrapping is invalid") from exc
        return record

    def list_requests(
        self,
        *,
        actor: ActorContext,
        page: int,
        page_size: int,
    ) -> tuple[list[RecoveryRequestRecord], int]:
        requested_by = None if actor.role in _REVIEWER_ROLES else actor.user_id
        return self.repository.list_request_records(
            requested_by=requested_by,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
