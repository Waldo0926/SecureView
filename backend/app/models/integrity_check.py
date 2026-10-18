from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class IntegrityCheck(Base):
    __tablename__ = "integrity_checks"
    __table_args__ = (
        Index("idx_integrity_checks_file_id", "file_id"),
        Index("idx_integrity_checks_checked_by", "checked_by"),
        Index("idx_integrity_checks_result", "result"),
        Index("idx_integrity_checks_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)

    file_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey(
            "files.id",
            name="fk_integrity_checks_file",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    checked_by: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_integrity_checks_checked_by",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    expected_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    actual_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    result: Mapped[str] = mapped_column(
        Enum("VALID", "MODIFIED", "MISSING", "ERROR", name="integrity_check_result_enum"),
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )

    file = relationship("File", back_populates="integrity_checks")
    checked_by_user = relationship(
        "User", back_populates="integrity_checks", foreign_keys=[checked_by]
    )
