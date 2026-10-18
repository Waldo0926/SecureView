from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FileAccessGrant(Base):
    __tablename__ = "file_access_grants"
    __table_args__ = (
        UniqueConstraint("file_id", "user_id", name="uq_file_access_grants_file_user"),
        CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="ck_file_access_grants_status_revoked_at",
        ),
        CheckConstraint("revision >= 1", name="ck_file_access_grants_revision"),
        Index("idx_file_access_grants_file_id", "file_id"),
        Index("idx_file_access_grants_folder_id", "folder_id"),
        Index("idx_file_access_grants_user_id", "user_id"),
        Index(
            "idx_file_access_grants_user_status_file",
            "user_id",
            "status",
            "file_id",
        ),
        Index("idx_file_access_grants_granted_by", "granted_by"),
        Index("idx_file_access_grants_status", "status"),
        Index("idx_file_access_grants_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )

    file_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "files.id",
            name="fk_file_access_grants_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_file_access_grants_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    granted_by: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_file_access_grants_granted_by",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

    can_download: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    can_share: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    can_revoke: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    can_manage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "REVOKED", name="file_access_grant_status_enum"),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=1, server_default="1"
    )
    # Where the grantee filed this file, in one of their own folders. Only a recipient's grant
    # uses it; the owner's placement stays in files.folder_id (revision 0010_shared_file_folders).
    folder_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "file_folders.id",
            name="fk_file_access_grants_folder",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    file = relationship("File", back_populates="access_grants")
    folder = relationship("FileFolder", back_populates="shared_placements")
    user = relationship("User", back_populates="access_grants", foreign_keys=[user_id])
    grantor = relationship("User", back_populates="granted_accesses", foreign_keys=[granted_by])
