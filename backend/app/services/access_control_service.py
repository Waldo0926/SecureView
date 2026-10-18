from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.enums import FileCapability
from app.domain.errors import FileResourceNotFoundError
from app.repositories.file_repository import FileAccessRecord, FileRepository
from app.services.audit_log_service import AuditLogService
from app.services.file_storage_service import FileStorageService


class AccessControlService:
    """Require both a logical grant and a usable cryptographic wrapping."""

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        storage: FileStorageService,
        audit_service: AuditLogService,
        repository: FileRepository | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage
        self.audit = audit_service
        self.repository = repository or FileRepository(db)

    def require(
        self,
        *,
        user_id: int,
        file_id: UUID,
        capability: FileCapability = FileCapability.VIEW,
    ) -> FileAccessRecord:
        record = self.repository.get_active_access(file_id, user_id)
        if record is None:
            # Uniform not-found responses prevent probing file existence or distinguishing
            # a missing logical grant from a missing cryptographic wrapping.
            raise FileResourceNotFoundError()

        capability_field = {
            FileCapability.VIEW: None,
            FileCapability.DOWNLOAD: "can_download",
            FileCapability.SHARE: "can_share",
            FileCapability.REVOKE: "can_revoke",
            FileCapability.MANAGE: "can_manage",
        }[capability]
        if capability_field is not None and not bool(getattr(record.grant, capability_field)):
            raise FileResourceNotFoundError()
        return record
