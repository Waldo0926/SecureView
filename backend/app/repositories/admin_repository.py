from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.domain.enums import SessionStatus, SystemRole, UserStatus
from app.models.audit_log import AuditLog
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.integrity_check import IntegrityCheck
from app.models.recovery_request import RecoveryRequest
from app.models.user import User
from app.models.user_session import UserSession


@dataclass(frozen=True, slots=True)
class UserActivity:
    file_count: int
    stored_bytes: int
    shared_by_them: int
    shared_with_them: int
    active_sessions: int


@dataclass(frozen=True, slots=True)
class DamagedFileRow:
    file_uuid: str
    original_filename: str
    status: str
    owner_username: str
    last_result: str | None
    last_message: str | None
    last_checked_at: datetime | None


def _count_where(condition):
    """How many rows satisfy `condition`, as a number.

    `func.sum(<comparison>)` is typed Boolean by SQLAlchemy, so the driver's answer was coerced
    through bool(): any total above zero came back as 1. The dashboard therefore showed "1" for
    failed checks, events and failures however many there were, and a test that started from an
    empty database could not tell. Summing a CASE gives an integer column.
    """
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


# A list filter meaning "everything that has not been deleted": deleted accounts and files are
# kept as tombstones, and on a busy platform they outnumber the live ones.
CURRENT = "CURRENT"


class AdminRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_users(self, *, limit: int, offset: int, status: str | None = None) -> list[User]:
        statement = select(User)
        if status == CURRENT:
            statement = statement.where(User.status != UserStatus.DELETED)
        elif status is not None:
            statement = statement.where(User.status == status)
        return list(
            self.db.scalars(
                statement.order_by(User.created_at.desc(), User.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    def list_files(
        self, *, limit: int, offset: int, status: str | None = None
    ) -> list[tuple[File, User]]:
        statement = select(File, User).join(User, User.id == File.owner_id)
        if status == CURRENT:
            statement = statement.where(File.status != "DELETED")
        elif status is not None:
            statement = statement.where(File.status == status)
        rows = self.db.execute(
            statement.order_by(File.created_at.desc(), File.id.desc()).offset(offset).limit(limit)
        )
        return [row._tuple() for row in rows]

    # --- dashboard counts -------------------------------------------------------------------
    # Every method below is a single aggregate query that returns numbers, never rows, so the
    # dashboard cannot become a way to read file names, keys or addresses.

    def user_counts_by_status(self) -> dict[str, int]:
        rows = self.db.execute(select(User.status, func.count()).group_by(User.status))
        return {str(getattr(status, "value", status)): count for status, count in rows}

    def count_administrators(self) -> int:
        return self._count(
            select(func.count()).select_from(User).where(User.role == SystemRole.ADMIN)
        )

    def count_users_created_since(self, since: datetime) -> int:
        return self._count(select(func.count()).select_from(User).where(User.created_at >= since))

    def count_users_signed_in_since(self, since: datetime) -> int:
        return self._count(
            select(func.count()).select_from(User).where(User.last_login_at >= since)
        )

    def file_counts_by_status(self) -> dict[str, int]:
        rows = self.db.execute(select(File.status, func.count()).group_by(File.status))
        return {str(status): count for status, count in rows}

    def count_files_uploaded_since(self, since: datetime) -> int:
        return self._count(select(func.count()).select_from(File).where(File.created_at >= since))

    def stored_totals(self) -> tuple[int, int]:
        """Original and stored (ciphertext) bytes across files that still exist."""
        row = self.db.execute(
            select(
                func.coalesce(func.sum(File.file_size_bytes), 0),
                func.coalesce(func.sum(File.encrypted_size_bytes), 0),
            ).where(File.status != "DELETED")
        ).one()
        return int(row[0]), int(row[1])

    def file_counts_by_algorithm(self) -> dict[str, int]:
        rows = self.db.execute(
            select(File.encryption_algorithm, func.count())
            .where(File.status != "DELETED")
            .group_by(File.encryption_algorithm)
        )
        return {str(algorithm): count for algorithm, count in rows}

    def share_counts(self) -> tuple[int, int]:
        """(live grants held by someone other than the owner, distinct files they cover)."""
        row = self.db.execute(
            select(func.count(), func.count(func.distinct(FileAccessGrant.file_id)))
            .select_from(FileAccessGrant)
            .join(File, File.id == FileAccessGrant.file_id)
            .where(
                FileAccessGrant.status == "ACTIVE",
                FileAccessGrant.user_id != File.owner_id,
                File.status != "DELETED",
            )
        ).one()
        return int(row[0]), int(row[1])

    def integrity_check_counts_since(self, since: datetime) -> tuple[int, int]:
        """(checks run, checks that did not come back VALID) since the cutoff."""
        row = self.db.execute(
            select(
                func.count(),
                _count_where(IntegrityCheck.result != "VALID"),
            ).where(IntegrityCheck.created_at >= since)
        ).one()
        return int(row[0]), int(row[1])

    def count_pending_recovery_requests(self) -> int:
        return self._count(
            select(func.count())
            .select_from(RecoveryRequest)
            .where(RecoveryRequest.status == "PENDING")
        )

    def audit_counts(self, since: datetime) -> tuple[int, int, int]:
        """(all events, events since the cutoff, FAIL events since the cutoff)."""
        row = self.db.execute(
            select(
                func.count(),
                _count_where(AuditLog.created_at >= since),
                _count_where((AuditLog.created_at >= since) & (AuditLog.result == "FAIL")),
            )
        ).one()
        return int(row[0]), int(row[1]), int(row[2])

    def recent_audit_failures(self, *, limit: int) -> list[tuple[str, str, datetime, str | None]]:
        """The newest FAIL events as (action, result, when, actor username) and nothing more."""
        rows = self.db.execute(
            select(AuditLog.action, AuditLog.result, AuditLog.created_at, User.username)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(AuditLog.result == "FAIL")
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        return [
            (action, result, created_at, username) for action, result, created_at, username in rows
        ]

    # --- integrity report -------------------------------------------------------------------

    def damaged_files(self, *, limit: int) -> list[DamagedFileRow]:
        """Files marked CORRUPTED, or whose newest check could not read the object.

        A MISSING or ERROR finding does not change `files.status` (see IntegrityService),
        so the newest check is part of the answer, not just the status column. Only the
        columns the report shows are selected: no key, nonce or password hash is loaded.
        """
        # The inner table is an alias so the newest-check subquery is never correlated with the
        # outer join's integrity_checks, and the join also states file_id = files.id: the result
        # is the same, but without it SQLAlchemy cannot see the join and warns of a cartesian
        # product.
        inner = aliased(IntegrityCheck)
        newest = (
            select(func.max(inner.id))
            .where(inner.file_id == File.id)
            .correlate(File)
            .scalar_subquery()
        )
        rows = self.db.execute(
            select(
                File.file_uuid,
                File.original_filename,
                File.status,
                User.username,
                IntegrityCheck.result,
                IntegrityCheck.message,
                IntegrityCheck.created_at,
            )
            .join(User, User.id == File.owner_id)
            .outerjoin(
                IntegrityCheck,
                and_(IntegrityCheck.file_id == File.id, IntegrityCheck.id == newest),
            )
            .where(
                File.status != "DELETED",
                or_(
                    File.status == "CORRUPTED",
                    IntegrityCheck.result.in_(("MODIFIED", "MISSING", "ERROR")),
                ),
            )
            .order_by(File.updated_at.desc(), File.id.desc())
            .limit(limit)
        )
        return [DamagedFileRow(*row) for row in rows]

    def integrity_coverage(self, since: datetime) -> tuple[int, int, int, datetime | None]:
        """(files that can be checked, never checked, checked since the cutoff, last sweep)."""
        candidates = self._count(
            select(func.count()).select_from(File).where(File.status.in_(("ACTIVE", "CORRUPTED")))
        )
        checked_ever = self._count(
            select(func.count(func.distinct(IntegrityCheck.file_id)))
            .select_from(IntegrityCheck)
            .join(File, File.id == IntegrityCheck.file_id)
            .where(File.status.in_(("ACTIVE", "CORRUPTED")))
        )
        checked_recently = self._count(
            select(func.count(func.distinct(IntegrityCheck.file_id)))
            .select_from(IntegrityCheck)
            .join(File, File.id == IntegrityCheck.file_id)
            .where(File.status.in_(("ACTIVE", "CORRUPTED")), IntegrityCheck.created_at >= since)
        )
        last_sweep = self.db.scalar(
            select(func.max(AuditLog.created_at)).where(
                AuditLog.action == "INTEGRITY_SWEEP_COMPLETED"
            )
        )
        return candidates, max(candidates - checked_ever, 0), checked_recently, last_sweep

    def _count(self, statement) -> int:
        return int(self.db.scalar(statement) or 0)

    def get_user_by_uuid(self, user_uuid: UUID) -> User | None:
        return self.db.scalar(select(User).where(User.user_uuid == str(user_uuid)))

    def user_activity(self, user_id: int, *, now: datetime) -> UserActivity:
        """Counts for one account's detail view: numbers only, never file names or keys."""
        files = self.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(File.encrypted_size_bytes), 0),
            ).where(File.owner_id == user_id, File.status != "DELETED")
        ).one()
        shared_by_them = self._count(
            select(func.count())
            .select_from(FileAccessGrant)
            .join(File, File.id == FileAccessGrant.file_id)
            .where(
                File.owner_id == user_id,
                FileAccessGrant.user_id != user_id,
                FileAccessGrant.status == "ACTIVE",
                File.status != "DELETED",
            )
        )
        shared_with_them = self._count(
            select(func.count())
            .select_from(FileAccessGrant)
            .join(File, File.id == FileAccessGrant.file_id)
            .where(
                FileAccessGrant.user_id == user_id,
                File.owner_id != user_id,
                FileAccessGrant.status == "ACTIVE",
                File.status != "DELETED",
            )
        )
        sessions = self._count(
            select(func.count())
            .select_from(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.status == SessionStatus.ACTIVE,
                UserSession.absolute_expires_at > now,
            )
        )
        return UserActivity(
            file_count=int(files[0]),
            stored_bytes=int(files[1]),
            shared_by_them=shared_by_them,
            shared_with_them=shared_with_them,
            active_sessions=sessions,
        )

    def lock_user_by_uuid(self, user_uuid: UUID) -> User | None:
        return self.db.scalar(
            select(User)
            .where(User.user_uuid == str(user_uuid))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
