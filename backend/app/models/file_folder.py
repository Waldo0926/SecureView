from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FileFolder(Base):
    """A user-owned organizational folder; it never changes ciphertext storage."""

    __tablename__ = "file_folders"
    __table_args__ = (
        UniqueConstraint("folder_uuid", name="uq_file_folders_folder_uuid"),
        UniqueConstraint("owner_id", "name", name="uq_file_folders_owner_name"),
        Index("idx_file_folders_owner_name", "owner_id", "name"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    folder_uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False, default=lambda: str(uuid4()))
    owner_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id", name="fk_file_folders_owner", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()"), onupdate=func.now()
    )

    owner = relationship("User", back_populates="file_folders")
    files = relationship("File", back_populates="folder")
    shared_placements = relationship("FileAccessGrant", back_populates="folder")
