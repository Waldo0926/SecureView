from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.audit_chain_head import AuditChainHead
from app.models.audit_log import AuditLog
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.user import User

_FILE_RECOVERY_ACTIONS = (
    "RECOVERY_REQUEST_CREATED",
    "RECOVERY_REQUEST_APPROVED",
    "RECOVERY_REQUEST_REJECTED",
    "RECOVERY_REQUEST_CANCELLED",
    "RECOVERY_REQUEST_EXECUTED",
)


def _about_a_file():
    """Rows whose resource id names a file: the file itself, its shares, its integrity checks,
    and the recovery steps taken on it.

    A resource id is only a string, and an upload's file id is chosen by the client. Matching on
    the id alone would let someone upload a file whose id equals another person's user or key
    id and then read that person's account rows as if they were about the file.
    """
    return or_(
        AuditLog.resource_type.in_(("FILE", "SHARE", "INTEGRITY")),
        and_(
            AuditLog.resource_type == "RECOVERY",
            AuditLog.action.in_(_FILE_RECOVERY_ACTIONS),
        ),
    )


def _contains(search: str) -> str:
    """A LIKE pattern for "contains this text", with the wildcards taken literally.

    `%` and `_` are LIKE metacharacters, so an unescaped `_` would match every single
    character and `%` would match everything. Both are ordinary characters in a file name or a
    description (`report_v2.pdf`), and a person typing one means it literally. Same escaping
    as `FileRepository._filename_contains`. Both columns collate `utf8mb4_unicode_ci`, so the
    match is already case-insensitive without lowering either side.
    """
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_logs(
        self,
        *,
        actor_user_id: int | None,
        admin: bool,
        limit: int,
        offset: int,
        resource_id: str | None = None,
        action: str | None = None,
        result: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        keyword: str | None = None,
    ) -> list[tuple[AuditLog, User | None, User | None]]:
        actor_user = aliased(User)
        target_user = aliased(User)
        statement = (
            select(AuditLog, actor_user, target_user)
            .outerjoin(actor_user, actor_user.id == AuditLog.actor_user_id)
            .outerjoin(target_user, target_user.id == AuditLog.target_user_id)
        )
        if keyword is not None:
            # The file name is not on the audit row. It is looked up from `files` by the
            # resource id, the same way `file_labels` names a row after the fact, so a search
            # for "report" finds every row about `report.pdf` as well as rows whose description
            # mentions it. An outer join: a row about no file still matches on its description.
            named_file = aliased(File)
            statement = statement.outerjoin(
                named_file, named_file.file_uuid == AuditLog.resource_id
            )
        # One rule, applied the same way whether or not a file was named:
        #
        #   you see what you did, what was done to you, and everything done to a file you
        #   own.
        #
        # The file-scoped query used to skip this filter entirely on the reasoning that
        # AuditQueryService had already checked entitlement. But entitlement is not
        # ownership: a recipient holds an ACTIVE grant, so any recipient could read the
        # whole trail -- learning that other recipients existed and when each of them
        # downloaded. Owning the file is what earns the right to see who touched it.
        # "Done to a file" means a row about a file, not any row that shares its id.
        if not admin:
            owned_files = select(File.file_uuid).where(File.owner_id == actor_user_id)
            statement = statement.where(
                or_(
                    AuditLog.actor_user_id == actor_user_id,
                    AuditLog.target_user_id == actor_user_id,
                    and_(AuditLog.resource_id.in_(owned_files), _about_a_file()),
                )
            )
        if resource_id is not None:
            statement = statement.where(AuditLog.resource_id == resource_id, _about_a_file())
        # The optional filters only ever narrow. They are added after the visibility rule
        # above, so a non-admin who filters still sees a subset of their own page and never a
        # row that belongs to somebody else.
        if action is not None:
            statement = statement.where(AuditLog.action == action)
        if result is not None:
            statement = statement.where(AuditLog.result == result)
        if created_from is not None:
            statement = statement.where(AuditLog.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(AuditLog.created_at <= created_to)
        if keyword is not None:
            pattern = _contains(keyword)
            statement = statement.where(
                or_(
                    AuditLog.description.like(pattern, escape="\\"),
                    named_file.original_filename.like(pattern, escape="\\"),
                )
            )
        rows = self.db.execute(
            statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [tuple(row) for row in rows]

    def file_labels(self, file_uuids: Iterable[str]) -> dict[str, tuple[str, bool]]:
        """Original filename and whether it was deleted, for the files these audit rows are about.

        Deleting a file is a soft delete: the row, and so its name, stays. That is what lets the
        access-records page say which file a row was about after the file is gone, without asking
        for every deleted file one by one (each of those lookups answered 404).
        """
        wanted = {file_uuid for file_uuid in file_uuids if file_uuid}
        if not wanted:
            return {}
        rows = self.db.execute(
            select(File.file_uuid, File.original_filename, File.status).where(
                File.file_uuid.in_(wanted)
            )
        )
        return {
            str(file_uuid): (str(name), status == "DELETED") for file_uuid, name, status in rows
        }

    def can_access_file(self, user_id: int, file_uuid: UUID) -> bool:
        return (
            self.db.scalar(
                select(File.id)
                .join(
                    FileAccessGrant,
                    (FileAccessGrant.file_id == File.id)
                    & (FileAccessGrant.user_id == user_id)
                    & (FileAccessGrant.status == "ACTIVE"),
                )
                .join(
                    FileKeyWrapping,
                    (FileKeyWrapping.file_id == File.id)
                    & (FileKeyWrapping.recipient_user_id == user_id)
                    & (FileKeyWrapping.status == "ACTIVE"),
                )
                .where(File.file_uuid == str(file_uuid), File.status != "DELETED")
                .limit(1)
            )
            is not None
        )

    def chain_rows(self) -> tuple[list[AuditLog], AuditChainHead | None]:
        logs = list(self.db.scalars(select(AuditLog).order_by(AuditLog.id.asc())))
        head = self.db.scalar(select(AuditChainHead).where(AuditChainHead.id == 1))
        return logs, head
