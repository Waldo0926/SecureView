from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.recovery_key import RecoveryKey
from app.models.recovery_request import RecoveryRequest
from app.models.user import User
from app.models.user_key import UserKey


@dataclass(frozen=True, slots=True)
class RecoveryRequestRecord:
    request: RecoveryRequest
    file: File
    requester: User
    target_key: UserKey | None
    reviewer: User | None
    executor: User | None


@dataclass(frozen=True, slots=True)
class RecoveryExecutionRecord:
    request: RecoveryRequest
    file: File
    requester: User
    target_key: UserKey
    source_wrapping: FileKeyWrapping
    recovery_key: RecoveryKey


@dataclass(frozen=True, slots=True)
class RecoveryRequestLocator:
    file_id: int
    requested_by: int
    target_user_key_id: int | None


class RecoveryRepository:
    """Persistence adapter for recovery workflows; transaction ownership stays in service."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def flush(self) -> None:
        self.db.flush()

    def add_recovery_key(self, key: RecoveryKey) -> None:
        self.db.add(key)

    def add_request(self, request: RecoveryRequest) -> None:
        self.db.add(request)

    def add_grant(self, grant: FileAccessGrant) -> None:
        self.db.add(grant)

    def add_wrapping(self, wrapping: FileKeyWrapping) -> None:
        self.db.add(wrapping)

    def get_active_recovery_key(self) -> RecoveryKey | None:
        return self.db.scalar(
            select(RecoveryKey)
            .where(RecoveryKey.status == "ACTIVE")
            .order_by(RecoveryKey.created_at.desc(), RecoveryKey.id.desc())
            .limit(1)
        )

    def lock_active_recovery_keys(self) -> list[RecoveryKey]:
        return list(
            self.db.scalars(
                select(RecoveryKey)
                .where(RecoveryKey.status == "ACTIVE")
                .order_by(RecoveryKey.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def get_recovery_key_by_uuid(
        self,
        key_id: UUID,
        *,
        for_update: bool = False,
    ) -> RecoveryKey | None:
        statement = select(RecoveryKey).where(RecoveryKey.key_uuid == str(key_id)).limit(1)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(statement)

    def get_recovery_key_by_fingerprint(self, fingerprint: str) -> RecoveryKey | None:
        return self.db.scalar(
            select(RecoveryKey).where(RecoveryKey.fingerprint == fingerprint).limit(1)
        )

    def lock_file(self, file_id: UUID) -> File | None:
        return self.db.scalar(
            select(File)
            .where(File.file_uuid == str(file_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_file_by_id(self, file_id: int) -> File | None:
        return self.db.scalar(
            select(File)
            .where(File.id == file_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_grant(self, file_id: int, user_id: int) -> FileAccessGrant | None:
        return self.db.scalar(
            select(FileAccessGrant)
            .where(FileAccessGrant.file_id == file_id, FileAccessGrant.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_active_user_wrapping(
        self,
        file_id: int,
        user_id: int,
    ) -> FileKeyWrapping | None:
        return self.db.scalar(
            select(FileKeyWrapping)
            .join(UserKey, UserKey.id == FileKeyWrapping.user_key_id)
            .where(
                FileKeyWrapping.file_id == file_id,
                FileKeyWrapping.recipient_type == "USER",
                FileKeyWrapping.recipient_user_id == user_id,
                FileKeyWrapping.status == "ACTIVE",
                UserKey.user_id == user_id,
                UserKey.status == "ACTIVE",
            )
            .order_by(FileKeyWrapping.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )

    def lock_active_recovery_wrapping(self, file_id: int) -> FileKeyWrapping | None:
        return self.db.scalar(
            select(FileKeyWrapping)
            .where(
                FileKeyWrapping.file_id == file_id,
                FileKeyWrapping.recipient_type == "RECOVERY",
                FileKeyWrapping.status == "ACTIVE",
            )
            .order_by(FileKeyWrapping.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )

    def has_active_download_entitlement(self, file_id: int, user_id: int) -> bool:
        return (
            self.db.scalar(
                select(FileAccessGrant.id)
                .join(
                    FileKeyWrapping,
                    (FileKeyWrapping.file_id == FileAccessGrant.file_id)
                    & (FileKeyWrapping.recipient_user_id == FileAccessGrant.user_id),
                )
                .join(UserKey, UserKey.id == FileKeyWrapping.user_key_id)
                .where(
                    FileAccessGrant.file_id == file_id,
                    FileAccessGrant.user_id == user_id,
                    FileAccessGrant.status == "ACTIVE",
                    FileAccessGrant.can_download.is_(True),
                    FileKeyWrapping.recipient_type == "USER",
                    FileKeyWrapping.status == "ACTIVE",
                    UserKey.user_id == user_id,
                    UserKey.status == "ACTIVE",
                )
                .limit(1)
            )
            is not None
        )

    def lock_active_target_key(self, user_id: int, key_id: UUID) -> UserKey | None:
        return self.db.scalar(
            select(UserKey)
            .where(
                UserKey.user_id == user_id,
                UserKey.key_uuid == str(key_id),
                UserKey.status == "ACTIVE",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )

    def lock_pending_request(
        self,
        *,
        file_id: int,
        requested_by: int,
        now: datetime,
    ) -> RecoveryRequest | None:
        return self.db.scalar(
            select(RecoveryRequest)
            .where(
                RecoveryRequest.file_id == file_id,
                RecoveryRequest.requested_by == requested_by,
                RecoveryRequest.status == "PENDING",
                RecoveryRequest.expires_at > now,
            )
            .order_by(RecoveryRequest.id.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )

    def lock_request(self, request_id: UUID) -> RecoveryRequest | None:
        return self.db.scalar(
            select(RecoveryRequest)
            .where(RecoveryRequest.request_uuid == str(request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )

    def get_request_locator(self, request_id: UUID) -> RecoveryRequestLocator | None:
        row = self.db.execute(
            select(
                RecoveryRequest.file_id,
                RecoveryRequest.requested_by,
                RecoveryRequest.target_user_key_id,
            )
            .where(RecoveryRequest.request_uuid == str(request_id))
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return RecoveryRequestLocator(
            file_id=row[0],
            requested_by=row[1],
            target_user_key_id=row[2],
        )

    def lock_recovery_source(
        self,
        *,
        file_id: int,
        recovery_key_id: UUID,
    ) -> tuple[FileKeyWrapping, RecoveryKey] | None:
        row = self.db.execute(
            select(FileKeyWrapping, RecoveryKey)
            .join(RecoveryKey, RecoveryKey.id == FileKeyWrapping.recovery_key_id)
            .where(
                FileKeyWrapping.file_id == file_id,
                FileKeyWrapping.recipient_type == "RECOVERY",
                FileKeyWrapping.status == "ACTIVE",
                RecoveryKey.key_uuid == str(recovery_key_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        ).one_or_none()
        return None if row is None else tuple(row)

    def get_execution_record(self, request_id: UUID) -> RecoveryExecutionRecord | None:
        row = self.db.execute(
            select(
                RecoveryRequest,
                File,
                User,
                UserKey,
                FileKeyWrapping,
                RecoveryKey,
            )
            .join(File, File.id == RecoveryRequest.file_id)
            .join(User, User.id == RecoveryRequest.requested_by)
            .join(
                UserKey,
                (UserKey.id == RecoveryRequest.target_user_key_id)
                & (UserKey.user_id == RecoveryRequest.requested_by),
            )
            .join(
                FileKeyWrapping,
                (FileKeyWrapping.file_id == RecoveryRequest.file_id)
                & (FileKeyWrapping.recipient_type == "RECOVERY")
                & (FileKeyWrapping.status == "ACTIVE"),
            )
            .join(RecoveryKey, RecoveryKey.id == FileKeyWrapping.recovery_key_id)
            .where(RecoveryRequest.request_uuid == str(request_id))
            .order_by(FileKeyWrapping.id.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return RecoveryExecutionRecord(
            request=row[0],
            file=row[1],
            requester=row[2],
            target_key=row[3],
            source_wrapping=row[4],
            recovery_key=row[5],
        )

    def lock_user_wrappings(self, file_id: int, user_id: int) -> list[FileKeyWrapping]:
        return list(
            self.db.scalars(
                select(FileKeyWrapping)
                .where(
                    FileKeyWrapping.file_id == file_id,
                    FileKeyWrapping.recipient_type == "USER",
                    FileKeyWrapping.recipient_user_id == user_id,
                )
                .order_by(FileKeyWrapping.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def get_wrapping(self, wrapping_id: int) -> FileKeyWrapping | None:
        return self.db.scalar(
            select(FileKeyWrapping).where(FileKeyWrapping.id == wrapping_id).limit(1)
        )

    @staticmethod
    def _request_record_statement():
        requester = aliased(User, name="recovery_requester")
        reviewer = aliased(User, name="recovery_reviewer")
        executor = aliased(User, name="recovery_executor")
        return (
            select(RecoveryRequest, File, requester, UserKey, reviewer, executor)
            .join(File, File.id == RecoveryRequest.file_id)
            .join(requester, requester.id == RecoveryRequest.requested_by)
            .outerjoin(UserKey, UserKey.id == RecoveryRequest.target_user_key_id)
            .outerjoin(reviewer, reviewer.id == RecoveryRequest.approved_by)
            .outerjoin(executor, executor.id == RecoveryRequest.executed_by)
        )

    @staticmethod
    def _record(row) -> RecoveryRequestRecord:
        return RecoveryRequestRecord(
            request=row[0],
            file=row[1],
            requester=row[2],
            target_key=row[3],
            reviewer=row[4],
            executor=row[5],
        )

    def get_request_record(self, request_id: UUID) -> RecoveryRequestRecord | None:
        row = self.db.execute(
            self._request_record_statement()
            .where(RecoveryRequest.request_uuid == str(request_id))
            .limit(1)
        ).one_or_none()
        return None if row is None else self._record(row)

    def list_request_records(
        self,
        *,
        requested_by: int | None,
        offset: int,
        limit: int,
    ) -> tuple[list[RecoveryRequestRecord], int]:
        statement = self._request_record_statement()
        count_statement = select(func.count(RecoveryRequest.id))
        if requested_by is not None:
            statement = statement.where(RecoveryRequest.requested_by == requested_by)
            count_statement = count_statement.where(RecoveryRequest.requested_by == requested_by)
        total = int(self.db.scalar(count_statement) or 0)
        rows = self.db.execute(
            statement.order_by(RecoveryRequest.created_at.desc(), RecoveryRequest.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [self._record(row) for row in rows], total
