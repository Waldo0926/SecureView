from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import UserStatus
from app.models.audit_log import AuditLog
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.user import User
from app.models.user_key import UserKey


class SharingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def lock_file(self, file_uuid: UUID) -> File | None:
        return self.db.scalar(
            select(File)
            .where(File.file_uuid == str(file_uuid))
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

    def has_active_wrapping(self, file_id: int, user_id: int) -> bool:
        return (
            self.db.scalar(
                select(FileKeyWrapping.id)
                .join(UserKey, UserKey.id == FileKeyWrapping.user_key_id)
                .where(
                    FileKeyWrapping.file_id == file_id,
                    FileKeyWrapping.recipient_type == "USER",
                    FileKeyWrapping.recipient_user_id == user_id,
                    FileKeyWrapping.status == "ACTIVE",
                    UserKey.status == "ACTIVE",
                )
                .limit(1)
            )
            is not None
        )

    def lock_target_user_and_key(
        self,
        target_user_uuid: UUID,
        target_key_uuid: UUID,
    ) -> tuple[User, UserKey] | None:
        row = self.db.execute(
            select(User, UserKey)
            .join(UserKey, UserKey.user_id == User.id)
            .where(
                User.user_uuid == str(target_user_uuid),
                User.status == UserStatus.ACTIVE,
                UserKey.key_uuid == str(target_key_uuid),
                UserKey.status == "ACTIVE",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else row._tuple()

    def get_user_by_uuid(self, user_uuid: UUID) -> User | None:
        return self.db.scalar(select(User).where(User.user_uuid == str(user_uuid)).limit(1))

    def count_shares_since(self, since: datetime) -> int:
        """How many shares have been recorded since `since`.

        Used as the stand-in for "notifications sent today". One share sends at most one
        notification, so this over-counts only when notifications were skipped or disabled --
        which errs toward sending fewer, and that is the safe direction when the thing being
        protected is verification-code delivery.
        """
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "FILE_SHARED", AuditLog.created_at >= since)
            )
            or 0
        )

    def get_user(self, user_id: int) -> User | None:
        """The sender, so a notification can name them rather than say "someone"."""
        return self.db.scalar(select(User).where(User.id == user_id).limit(1))

    def lock_user_wrappings(self, file_id: int, user_id: int) -> list[FileKeyWrapping]:
        return list(
            self.db.scalars(
                select(FileKeyWrapping)
                .where(
                    FileKeyWrapping.file_id == file_id,
                    FileKeyWrapping.recipient_type == "USER",
                    FileKeyWrapping.recipient_user_id == user_id,
                )
                .order_by(FileKeyWrapping.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def add_grant(self, grant: FileAccessGrant) -> None:
        self.db.add(grant)

    def add_wrapping(self, wrapping: FileKeyWrapping) -> None:
        self.db.add(wrapping)

    def list_shared_users(
        self,
        file_id: int,
        *,
        limit: int = 100,
    ) -> list[tuple[FileAccessGrant, User, UserKey]]:
        rows = self.db.execute(
            select(FileAccessGrant, User, UserKey)
            .join(User, User.id == FileAccessGrant.user_id)
            .join(
                FileKeyWrapping,
                (FileKeyWrapping.file_id == FileAccessGrant.file_id)
                & (FileKeyWrapping.recipient_user_id == FileAccessGrant.user_id)
                & (FileKeyWrapping.status == "ACTIVE"),
            )
            .join(UserKey, UserKey.id == FileKeyWrapping.user_key_id)
            .where(
                FileAccessGrant.file_id == file_id,
                FileAccessGrant.status == "ACTIVE",
                UserKey.status == "ACTIVE",
            )
            .order_by(User.username.asc(), User.id.asc())
            .limit(limit)
        )
        return [row._tuple() for row in rows]
