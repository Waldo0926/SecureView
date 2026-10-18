from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db_retry import run_with_deadlock_retry
from app.core.time import to_api_utc, to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import FileCapability
from app.domain.errors import IntegrityVerificationError, StorageUnavailableError
from app.models.file import File
from app.models.integrity_check import IntegrityCheck
from app.repositories.file_repository import FileAccessRecord, FileRepository
from app.schemas.file_schema import IntegrityCheckOut
from app.services.access_control_service import AccessControlService
from app.services.audit_log_service import AuditLogService
from app.services.file_storage_service import (
    FileStorageService,
    StorageObjectError,
    StorageObjectMissingError,
    VerifiedCiphertext,
)

ANCHOR_MISMATCH_MESSAGE = (
    "The digest recorded for this file differs from the one the audit chain recorded at upload"
)


@dataclass(slots=True)
class SweepSummary:
    """What one bounded pass over the stored objects found. Counts and ids, nothing else."""

    scanned: int = 0
    valid: int = 0
    modified: int = 0
    missing: int = 0
    error: int = 0
    candidates: int = 0
    stopped_early: bool = False
    damaged_file_ids: list[str] = field(default_factory=list)

    @property
    def damaged(self) -> int:
        return self.modified + self.missing + self.error


class IntegrityService:
    """Verify and persist ciphertext integrity without ever reading plaintext."""

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        storage: FileStorageService,
        audit_service: AuditLogService,
        repository: FileRepository | None = None,
        access_control: AccessControlService | None = None,
        clock=utc_now,
    ) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage
        self.audit = audit_service
        self.repository = repository or FileRepository(db)
        self.access = access_control or AccessControlService(
            db=db,
            settings=settings,
            storage=storage,
            audit_service=audit_service,
            repository=self.repository,
        )
        self.clock = clock

    def check(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        context: RequestContext,
    ) -> IntegrityCheckOut:
        record = self.access.require(
            user_id=actor.user_id,
            file_id=file_id,
            capability=FileCapability.VIEW,
        )
        expected = record.file.encrypted_sha256
        actual: str | None = None
        message: str | None = None
        try:
            actual, size = self.storage.hash_object(record.file.storage_object_key)
            if actual == expected and size == record.file.encrypted_size_bytes:
                result = "VALID"
            else:
                result = "MODIFIED"
                message = "The encrypted object does not match its recorded digest or size"
        except StorageObjectMissingError:
            result = "MISSING"
            message = "The encrypted object is missing"
        except StorageObjectError:
            result = "ERROR"
            message = "The encrypted object could not be verified"
        if result == "VALID" and self._anchor_conflicts(record.file):
            result = "MODIFIED"
            message = ANCHOR_MISMATCH_MESSAGE

        checked_at = self._now()
        try:
            check = self._add_check(
                record=record,
                actor=actor,
                checked_at=checked_at,
                result=result,
                actual=actual,
                message=message,
            )
            self._apply_status(record.file, result, checked_at)
            self.audit.append(
                action="FILE_INTEGRITY_CHECKED",
                result="SUCCESS" if result == "VALID" else "FAIL",
                actor_user_id=actor.user_id,
                resource_type="INTEGRITY",
                resource_id=str(file_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"integrity_result": result},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return IntegrityCheckOut(
            file_id=file_id,
            status=result,
            expected_hash=expected,
            actual_hash=actual,
            checked_at=to_api_utc(check.created_at) or to_api_utc(checked_at),
        )

    def open_verified_for_download(
        self,
        *,
        record: FileAccessRecord,
        actor: ActorContext,
        context: RequestContext,
    ) -> VerifiedCiphertext:
        """Verify using the same open descriptor that will subsequently be streamed."""
        verified: VerifiedCiphertext | None = None
        actual: str | None = None
        result = "ERROR"
        message = "The encrypted object could not be verified"
        try:
            verified = self.storage.open_verified(record.file.storage_object_key)
            actual = verified.sha256
            if (
                verified.sha256 == record.file.encrypted_sha256
                and verified.size_bytes == record.file.encrypted_size_bytes
            ):
                result = "VALID"
                message = "Ciphertext verified before download"
            else:
                result = "MODIFIED"
                message = "The encrypted object does not match its recorded digest or size"
            if result == "VALID" and self._anchor_conflicts(record.file):
                result = "MODIFIED"
                message = ANCHOR_MISMATCH_MESSAGE
        except StorageObjectMissingError:
            result = "MISSING"
            message = "The encrypted object is missing"
        except StorageObjectError:
            result = "ERROR"

        # The ciphertext is already read and verified above; only this transactional tail
        # -- recording the check, moving the file status, appending to the audit chain --
        # is retried. A download racing a share can deadlock over the chain-head lock and a
        # `users` row (issue #139); retrying here never re-reads the (possibly 500 MB)
        # object, only redoes these few small writes against a fresh lock order.
        try:
            return run_with_deadlock_retry(
                self.db,
                lambda: self._finalize_download_verification(
                    record=record,
                    actor=actor,
                    context=context,
                    result=result,
                    actual=actual,
                    message=message,
                    verified=verified,
                ),
            )
        except (IntegrityVerificationError, StorageUnavailableError):
            raise
        except Exception:
            self.db.rollback()
            if verified is not None:
                verified.stream.close()
            raise

    def _finalize_download_verification(
        self,
        *,
        record: FileAccessRecord,
        actor: ActorContext,
        context: RequestContext,
        result: str,
        actual: str | None,
        message: str | None,
        verified: VerifiedCiphertext | None,
    ) -> VerifiedCiphertext:
        checked_at = self._now()
        self._add_check(
            record=record,
            actor=actor,
            checked_at=checked_at,
            result=result,
            actual=actual,
            message=message,
        )
        self._apply_status(record.file, result, checked_at)
        if result != "VALID":
            self.audit.append(
                action="FILE_DOWNLOAD_INTEGRITY_FAILED",
                result="FAIL",
                actor_user_id=actor.user_id,
                resource_type="FILE",
                resource_id=record.file.file_uuid,
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"integrity_result": result},
            )
            self.db.commit()
            if verified is not None:
                verified.stream.close()
            if result == "ERROR":
                raise StorageUnavailableError()
            raise IntegrityVerificationError()

        self.audit.append(
            action="FILE_DOWNLOAD_AUTHORIZED",
            result="SUCCESS",
            actor_user_id=actor.user_id,
            resource_type="FILE",
            resource_id=record.file.file_uuid,
            context_ip_address=context.ip_address,
            context_user_agent=context.user_agent,
            metadata={"ciphertext_size": verified.size_bytes if verified else 0},
        )
        self.db.commit()
        if verified is None:  # pragma: no cover - result invariant
            raise RuntimeError("Verified ciphertext stream was not created")
        return verified

    def _anchor_conflicts(self, file_record: File) -> bool:
        anchor = self.repository.upload_anchor_sha256(file_record.file_uuid)
        return anchor is not None and anchor != file_record.encrypted_sha256

    def sweep(
        self,
        *,
        actor_user_id: int | None,
        context: RequestContext,
        limit: int,
        budget_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> SweepSummary:
        """Verify stored objects without a requesting user, least recently checked first.

        This is the proactive half of tamper detection: until now an object was only looked
        at when its owner downloaded it or clicked the check. It reads ciphertext only, needs
        no key, and never changes an object -- it records the finding in `integrity_checks`
        and, for MODIFIED, in the file status, exactly as a user-triggered check does.

        Each file is committed on its own, so a long pass makes progress that survives a
        failure partway, and the audit chain lock is held for one row at a time. Only
        findings and one summary row go to the audit log: a healthy file produces an
        `integrity_checks` row (that is what "last verified" is read from) but not an
        audit event, or a daily pass would bury the log in "everything is fine".
        """
        started = monotonic()
        summary = SweepSummary(candidates=self.repository.count_scan_candidates())
        for file_record in self.repository.list_scan_candidates(limit=limit):
            if budget_seconds is not None and monotonic() - started >= budget_seconds:
                summary.stopped_early = True
                break
            result = self.verify_and_record(
                file_record, actor_user_id=actor_user_id, context=context, source="sweep"
            )
            summary.scanned += 1
            if result == "VALID":
                summary.valid += 1
            else:
                setattr(summary, result.lower(), getattr(summary, result.lower()) + 1)
                summary.damaged_file_ids.append(file_record.file_uuid)
        try:
            self.audit.append(
                action="INTEGRITY_SWEEP_COMPLETED",
                result="SUCCESS" if summary.damaged == 0 else "FAIL",
                actor_user_id=actor_user_id,
                resource_type="SYSTEM",
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "scanned": summary.scanned,
                    "valid": summary.valid,
                    "modified": summary.modified,
                    "missing": summary.missing,
                    "error": summary.error,
                    "candidates": summary.candidates,
                    "stopped_early": summary.stopped_early,
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return summary

    def verify_and_record(
        self,
        file_record: File,
        *,
        actor_user_id: int | None,
        context: RequestContext,
        source: str,
    ) -> str:
        """Verify one stored object, record the finding and commit; returns the result.

        Used by the sweep and by the file-restore script, so a restored object is judged by
        exactly the rule that condemned it and a healed file leaves a VALID check behind.
        """
        result, actual, message = self._verify_stored(file_record)
        checked_at = self._now()
        try:
            self.repository.add_integrity_check(
                IntegrityCheck(
                    file_id=file_record.id,
                    checked_by=actor_user_id,
                    expected_hash=file_record.encrypted_sha256,
                    actual_hash=actual,
                    result=result,
                    message=message,
                    created_at=checked_at,
                )
            )
            self._apply_status(file_record, result, checked_at)
            if result != "VALID":
                self.audit.append(
                    action="FILE_INTEGRITY_CHECKED",
                    result="FAIL",
                    actor_user_id=actor_user_id,
                    resource_type="INTEGRITY",
                    resource_id=file_record.file_uuid,
                    context_ip_address=context.ip_address,
                    context_user_agent=context.user_agent,
                    metadata={"integrity_result": result, "source": source},
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return result

    def _verify_stored(self, file_record: File) -> tuple[str, str | None, str | None]:
        """(result, actual digest, message) for one stored object, never raising on storage."""
        try:
            actual, size = self.storage.hash_object(file_record.storage_object_key)
        except StorageObjectMissingError:
            return "MISSING", None, "The encrypted object is missing"
        except StorageObjectError:
            return "ERROR", None, "The encrypted object could not be verified"
        if actual != file_record.encrypted_sha256 or size != file_record.encrypted_size_bytes:
            return (
                "MODIFIED",
                actual,
                "The encrypted object does not match its recorded digest or size",
            )
        if self._anchor_conflicts(file_record):
            return "MODIFIED", actual, ANCHOR_MISMATCH_MESSAGE
        return "VALID", actual, None

    def _add_check(
        self,
        *,
        record: FileAccessRecord,
        actor: ActorContext,
        checked_at: datetime,
        result: str,
        actual: str | None,
        message: str | None,
    ) -> IntegrityCheck:
        check = IntegrityCheck(
            file_id=record.file.id,
            checked_by=actor.user_id,
            expected_hash=record.file.encrypted_sha256,
            actual_hash=actual,
            result=result,
            message=message,
            created_at=checked_at,
        )
        self.repository.add_integrity_check(check)
        return check

    @staticmethod
    def _apply_status(file_record: File, result: str, now: datetime) -> None:
        """Move the durable status only for findings about the ciphertext itself.

        MODIFIED is evidence about content: the object is readable and its bytes no longer
        match the digest recorded at upload. MISSING and ERROR are statements about the
        environment -- an unmounted volume, a misconfigured root, a filesystem that answered
        with an errno -- and they say nothing about bytes nobody could read. Recording an
        environment condition in a per-file column is what made a momentary outage
        indistinguishable from destroyed data. Every result, MISSING included, is still
        recorded in `integrity_checks` and in the audit log, which is where a transient
        condition belongs and where an operator can see it repeat.

        VALID restores ACTIVE so the status stays a description of the ciphertext as it is
        now rather than the worst thing ever observed about it. A file already stranded at
        CORRUPTED by the previous rule heals on its next successful verification.
        """
        if result == "MODIFIED":
            target = "CORRUPTED"
        elif result == "VALID":
            target = "ACTIVE"
        else:
            return
        if file_record.status == target or file_record.status == "DELETED":
            return
        file_record.status = target
        file_record.updated_at = now
        if hasattr(file_record, "revision"):
            file_record.revision += 1

    def _now(self) -> datetime:
        return to_second_resolution_utc(self.clock())
