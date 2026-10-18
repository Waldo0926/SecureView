from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, case, delete, func, literal, select, union_all, update
from sqlalchemy.orm import Session, joinedload

from app.models.audit_log import AuditLog
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_folder import FileFolder
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.integrity_check import IntegrityCheck
from app.models.recovery_key import RecoveryKey
from app.models.user_key import UserKey


@dataclass(frozen=True, slots=True)
class FileAccessRecord:
    file: File
    grant: FileAccessGrant
    wrapping: FileKeyWrapping
    user_key: UserKey


class FileRepository:
    """SQLAlchemy persistence adapter for encrypted-file use cases.

    The repository deliberately never commits. Transaction ownership remains in the
    application service so a published storage object can be compensated on DB failure.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def flush(self) -> None:
        self.db.flush()

    def add_file(self, file_record: File) -> None:
        self.db.add(file_record)

    def add_grant(self, grant: FileAccessGrant) -> None:
        self.db.add(grant)

    def add_wrapping(self, wrapping: FileKeyWrapping) -> None:
        self.db.add(wrapping)

    def add_integrity_check(self, check: IntegrityCheck) -> None:
        self.db.add(check)

    def upload_anchor_sha256(self, file_uuid: str) -> str | None:
        """The ciphertext digest the audit chain recorded when this file was uploaded.

        `files.encrypted_sha256` is an ordinary column: whoever can rewrite a stored object
        and also holds a database write can make them agree. The upload's audit row is part
        of the hash chain and of the externally anchored checkpoints, so a digest recorded
        there is the one reference a database edit cannot move quietly. Files uploaded
        before the digest was recorded have no anchor and return None.
        """
        metadata = self.db.scalar(
            select(AuditLog.metadata_json)
            .where(
                AuditLog.resource_type == "FILE",
                AuditLog.resource_id == file_uuid,
                AuditLog.action == "FILE_UPLOADED",
                AuditLog.result == "SUCCESS",
            )
            .order_by(AuditLog.id)
            .limit(1)
        )
        value = (metadata or {}).get("ciphertext_sha256") if isinstance(metadata, dict) else None
        if (
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
        ):
            return value
        return None

    def list_scan_candidates(self, *, limit: int) -> list[File]:
        """Files whose stored bytes can still be checked, least recently checked first.

        DELETED files have no object to check. A file that was never checked sorts first,
        then the one verified longest ago, so repeated bounded scans cover everything.
        """
        last_check = (
            select(func.max(IntegrityCheck.created_at))
            .where(IntegrityCheck.file_id == File.id)
            .correlate(File)
            .scalar_subquery()
        )
        return list(
            self.db.scalars(
                select(File)
                .where(File.status.in_(("ACTIVE", "CORRUPTED")))
                .order_by(last_check.is_not(None), last_check, File.id)
                .limit(limit)
            )
        )

    def count_scan_candidates(self) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(File)
                .where(File.status.in_(("ACTIVE", "CORRUPTED")))
            )
            or 0
        )

    def release_connection(self) -> None:
        """End the current read-only transaction so its connection goes back to the pool.

        Only for a point where nothing is pending. The session factory sets
        expire_on_commit=False, so rows already loaded stay usable afterwards.
        """
        self.db.commit()

    def stored_bytes_for_owner(self, owner_id: int) -> int:
        """Ciphertext bytes the owner currently occupies (every file not deleted)."""
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(File.encrypted_size_bytes), 0)).where(
                    File.owner_id == owner_id, File.status != "DELETED"
                )
            )
            or 0
        )

    def uploaded_bytes_since(self, owner_id: int, since: datetime) -> int:
        """Plaintext bytes the owner uploaded since `since`, deleted files included."""
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(File.file_size_bytes), 0)).where(
                    File.owner_id == owner_id, File.created_at >= since
                )
            )
            or 0
        )

    def file_uuid_exists(self, file_id: UUID) -> bool:
        return (
            self.db.scalar(select(File.id).where(File.file_uuid == str(file_id)).limit(1))
            is not None
        )

    def get_file_by_uuid(self, file_id: UUID, *, include_deleted: bool = False) -> File | None:
        statement = select(File).where(File.file_uuid == str(file_id))
        if not include_deleted:
            statement = statement.where(File.status != "DELETED")
        return self.db.scalar(statement.limit(1))

    def lock_owned_file(self, file_id: UUID, owner_id: int) -> File | None:
        return self.db.scalar(
            select(File)
            .where(File.file_uuid == str(file_id), File.owner_id == owner_id)
            .with_for_update()
        )

    def get_active_user_key(self, user_id: int, key_id: UUID) -> UserKey | None:
        key_uuid_column = getattr(UserKey, "key_uuid", None)
        if key_uuid_column is None:  # pragma: no cover - guarded by current schema migration
            raise RuntimeError("The user_keys.key_uuid migration is required")
        return self.db.scalar(
            select(UserKey)
            .where(
                UserKey.user_id == user_id,
                key_uuid_column == str(key_id),
                UserKey.status == "ACTIVE",
            )
            .limit(1)
        )

    def get_active_recovery_key(self, key_id: UUID) -> RecoveryKey | None:
        return self.db.scalar(
            select(RecoveryKey)
            .where(
                RecoveryKey.key_uuid == str(key_id),
                RecoveryKey.status == "ACTIVE",
            )
            .limit(1)
        )

    @staticmethod
    def _latest_active_wrapping_ids(user_id: int):
        """One active, usable wrapping per file, even for migrated wrapping history."""
        return (
            select(
                FileKeyWrapping.file_id.label("file_id"),
                func.max(FileKeyWrapping.id).label("wrapping_id"),
            )
            .join(UserKey, UserKey.id == FileKeyWrapping.user_key_id)
            .where(
                FileKeyWrapping.recipient_type == "USER",
                FileKeyWrapping.recipient_user_id == user_id,
                FileKeyWrapping.status == "ACTIVE",
                UserKey.user_id == user_id,
                UserKey.status == "ACTIVE",
            )
            .group_by(FileKeyWrapping.file_id)
            .subquery()
        )

    @classmethod
    def _active_access_statement(cls, user_id: int) -> Select:
        wrapping_ids = cls._latest_active_wrapping_ids(user_id)
        return (
            select(File, FileAccessGrant, FileKeyWrapping, UserKey)
            .join(
                FileAccessGrant,
                and_(
                    FileAccessGrant.file_id == File.id,
                    FileAccessGrant.user_id == user_id,
                ),
            )
            .join(wrapping_ids, wrapping_ids.c.file_id == File.id)
            .join(FileKeyWrapping, FileKeyWrapping.id == wrapping_ids.c.wrapping_id)
            .join(UserKey, UserKey.id == FileKeyWrapping.user_key_id)
            .where(
                # CORRUPTED is reachable on purpose. Hiding a damaged file removes the only
                # route its owner has to see the damage, re-check it, or delete it, and the
                # ciphertext is often still intact. Download stays protected by the
                # verification that runs on the way out, not by this filter.
                File.status.in_(("ACTIVE", "CORRUPTED")),
                FileAccessGrant.status == "ACTIVE",
                FileKeyWrapping.status == "ACTIVE",
                UserKey.status == "ACTIVE",
            )
        )

    def get_active_access(self, file_id: UUID, user_id: int) -> FileAccessRecord | None:
        row = self.db.execute(
            self._active_access_statement(user_id).where(File.file_uuid == str(file_id)).limit(1)
        ).one_or_none()
        if row is None:
            return None
        return FileAccessRecord(
            file=row[0],
            grant=row[1],
            wrapping=row[2],
            user_key=row[3],
        )

    @staticmethod
    def _filename_contains(search: str):
        """A LIKE predicate over the filename, with the wildcards taken literally.

        `%` and `_` are LIKE metacharacters, so an unescaped search for `_` matches every
        single character and a search for `%` matches everything. Both are ordinary
        characters in a filename and a user typing one means it literally. The column
        collates `utf8mb4_unicode_ci`, so matching is already case- and accent-insensitive
        without lowering either side and losing the index.
        """
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return File.original_filename.like(f"%{escaped}%", escape="\\")

    @staticmethod
    def placement(user_id: int):
        """The folder this user filed a file in: theirs if they own it, their grant's if shared.

        An owner's placement is `files.folder_id`. A recipient cannot write that (it belongs
        to the owner), so their placement is on their own grant (revision 0010).
        """
        return case((File.owner_id == user_id, File.folder_id), else_=FileAccessGrant.folder_id)

    def _owned_folder_pk(self, folder_id: UUID, user_id: int):
        return (
            select(FileFolder.id)
            .where(FileFolder.folder_uuid == str(folder_id), FileFolder.owner_id == user_id)
            .scalar_subquery()
        )

    def list_active_access(
        self,
        user_id: int,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        folder_id: UUID | None = None,
        unfiled: bool = False,
        scope: str = "all",
    ) -> tuple[list[FileAccessRecord], int, int, int]:
        """A page of files the user can open, its total, and the owned and shared totals.

        `scope` is applied here rather than by the client: splitting a page of mixed rows in
        the browser made the "Shared with me" tab show only the shared files that happened
        to fall on the current page, and the total count both kinds together.
        """
        base = self._active_access_statement(user_id)
        # Eager-load the owner and both possible placements: the listing names whoever shared
        # each file and its folder, and resolving those lazily would be a query per row.
        base = base.options(
            joinedload(File.owner), joinedload(File.folder), joinedload(FileAccessGrant.folder)
        )
        if search:
            base = base.where(self._filename_contains(search))

        owners = base.with_only_columns(File.owner_id.label("owner_id")).order_by(None).subquery()
        totals = self.db.execute(
            select(
                func.coalesce(func.sum(case((owners.c.owner_id == user_id, 1), else_=0)), 0),
                func.coalesce(func.sum(case((owners.c.owner_id != user_id, 1), else_=0)), 0),
            )
        ).one()
        owned_total, shared_total = int(totals[0]), int(totals[1])

        access_statement = base
        if scope == "mine":
            access_statement = access_statement.where(File.owner_id == user_id)
        elif scope == "shared":
            access_statement = access_statement.where(File.owner_id != user_id)
        placement = self.placement(user_id)
        if folder_id is not None:
            access_statement = access_statement.where(
                placement == self._owned_folder_pk(folder_id, user_id)
            )
        elif unfiled:
            access_statement = access_statement.where(placement.is_(None))
        count_statement = select(func.count()).select_from(
            access_statement.with_only_columns(File.id).order_by(None).subquery()
        )
        total = int(self.db.scalar(count_statement) or 0)
        rows = self.db.execute(
            access_statement.order_by(File.created_at.desc(), File.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return (
            [
                FileAccessRecord(
                    file=row[0],
                    grant=row[1],
                    wrapping=row[2],
                    user_key=row[3],
                )
                for row in rows
            ],
            total,
            owned_total,
            shared_total,
        )

    def _placements(self, user_id: int):
        """(folder id, whether owned) for every file this user can still see and has filed."""
        owned = select(File.folder_id.label("folder_id"), literal(1).label("owned")).where(
            File.owner_id == user_id,
            File.folder_id.is_not(None),
            File.status.in_(("ACTIVE", "CORRUPTED")),
        )
        shared = (
            select(FileAccessGrant.folder_id.label("folder_id"), literal(0).label("owned"))
            .join(File, File.id == FileAccessGrant.file_id)
            .where(
                FileAccessGrant.user_id == user_id,
                FileAccessGrant.status == "ACTIVE",
                FileAccessGrant.folder_id.is_not(None),
                File.owner_id != user_id,
                File.status.in_(("ACTIVE", "CORRUPTED")),
            )
        )
        return union_all(owned, shared).subquery()

    def list_folders(self, owner_id: int) -> list[tuple[FileFolder, int, int]]:
        """Each folder with how many of the user's own files and shared files it holds."""
        placed = self._placements(owner_id)
        rows = self.db.execute(
            select(
                FileFolder,
                func.coalesce(func.sum(case((placed.c.owned == 1, 1), else_=0)), 0),
                func.coalesce(func.sum(case((placed.c.owned == 0, 1), else_=0)), 0),
            )
            .outerjoin(placed, placed.c.folder_id == FileFolder.id)
            .where(FileFolder.owner_id == owner_id)
            .group_by(FileFolder.id)
            .order_by(FileFolder.name.asc(), FileFolder.id.asc())
        ).all()
        return [(row[0], int(row[1]), int(row[2])) for row in rows]

    def add_folder(self, folder: FileFolder) -> None:
        self.db.add(folder)

    def get_owned_folder(
        self, folder_id: UUID, owner_id: int, *, lock: bool = False
    ) -> FileFolder | None:
        statement = select(FileFolder).where(
            FileFolder.folder_uuid == str(folder_id), FileFolder.owner_id == owner_id
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement.limit(1))

    def delete_folder(self, folder: FileFolder) -> int:
        placed = self._placements(folder.owner_id)
        files_unfiled = int(
            self.db.scalar(
                select(func.count()).select_from(placed).where(placed.c.folder_id == folder.id)
            )
            or 0
        )
        # Both files.folder_id and file_access_grants.folder_id are ON DELETE SET NULL.
        self.db.execute(delete(FileFolder).where(FileFolder.id == folder.id))
        return files_unfiled

    def lock_recipient_grant(self, file_id: UUID, user_id: int) -> FileAccessGrant | None:
        """The caller's live grant on a file someone else owns, locked to file it away."""
        return self.db.scalar(
            select(FileAccessGrant)
            .join(File, File.id == FileAccessGrant.file_id)
            .where(
                File.file_uuid == str(file_id),
                File.owner_id != user_id,
                File.status.in_(("ACTIVE", "CORRUPTED")),
                FileAccessGrant.user_id == user_id,
                FileAccessGrant.status == "ACTIVE",
            )
            .with_for_update()
        )

    def lock_owned_files(self, owner_id: int) -> list[File]:
        """Every file this account still owns, locked for deletion.

        Used only by account deletion, which has to reach files the owner may never have
        opened in this session, so it cannot go one `lock_owned_file` at a time from a list
        the client supplied.
        """
        return list(
            self.db.scalars(
                select(File)
                .where(File.owner_id == owner_id, File.status != "DELETED")
                .with_for_update()
            ).all()
        )

    def revoke_file_access_rows(self, file_pk: int, *, revoked_at: datetime) -> None:
        grant_values: dict[str, object] = {
            "status": "REVOKED",
            "revoked_at": revoked_at,
        }
        if hasattr(FileAccessGrant, "updated_at"):
            grant_values["updated_at"] = revoked_at
        if hasattr(FileAccessGrant, "revision"):
            grant_values["revision"] = FileAccessGrant.revision + 1
        self.db.execute(
            update(FileAccessGrant)
            .where(FileAccessGrant.file_id == file_pk, FileAccessGrant.status == "ACTIVE")
            .values(**grant_values)
        )

        wrapping_values: dict[str, object] = {
            "status": "REVOKED",
            "revoked_at": revoked_at,
        }
        if hasattr(FileKeyWrapping, "updated_at"):
            wrapping_values["updated_at"] = revoked_at
        if hasattr(FileKeyWrapping, "revision"):
            wrapping_values["revision"] = FileKeyWrapping.revision + 1
        self.db.execute(
            update(FileKeyWrapping)
            .where(FileKeyWrapping.file_id == file_pk, FileKeyWrapping.status == "ACTIVE")
            .values(**wrapping_values)
        )
