from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FileKeyWrapping(Base):
    __tablename__ = "file_key_wrappings"
    __table_args__ = (
        UniqueConstraint(
            "file_id",
            "recipient_user_id",
            "user_key_id",
            name="uq_file_key_wrappings_file_user_key",
        ),
        UniqueConstraint(
            "file_id",
            "recovery_key_id",
            name="uq_file_key_wrappings_file_recovery_key",
        ),
        ForeignKeyConstraint(
            ["user_key_id", "recipient_user_id"],
            ["user_keys.id", "user_keys.user_id"],
            name="fk_file_key_wrappings_user_key_owner",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            "(recipient_type = 'USER' "
            "AND recipient_user_id IS NOT NULL "
            "AND user_key_id IS NOT NULL "
            "AND recovery_key_id IS NULL) OR "
            "(recipient_type = 'RECOVERY' "
            "AND recipient_user_id IS NULL "
            "AND user_key_id IS NULL "
            "AND recovery_key_id IS NOT NULL)",
            name="ck_file_key_wrappings_recipient_shape",
        ),
        CheckConstraint(
            "wrapping_algorithm = 'RSA-OAEP-SHA256' "
            "AND OCTET_LENGTH(wrapped_file_key) BETWEEN 256 AND 512",
            name="ck_file_key_wrappings_envelope",
        ),
        CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="ck_file_key_wrappings_status_revoked_at",
        ),
        CheckConstraint("revision >= 1", name="ck_file_key_wrappings_revision"),
        Index("idx_file_key_wrappings_file_id", "file_id"),
        Index("idx_file_key_wrappings_recipient_type", "recipient_type"),
        Index("idx_file_key_wrappings_recipient_user_id", "recipient_user_id"),
        Index("idx_file_key_wrappings_user_key_id", "user_key_id"),
        Index("idx_file_key_wrappings_recovery_key_id", "recovery_key_id"),
        Index("idx_file_key_wrappings_status", "status"),
        Index(
            "idx_file_key_wrappings_recipient_status_file_key",
            "recipient_user_id",
            "status",
            "file_id",
            "user_key_id",
        ),
        Index(
            "idx_file_key_wrappings_user_key_owner",
            "user_key_id",
            "recipient_user_id",
        ),
        Index("idx_file_key_wrappings_created_at", "created_at"),
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
            name="fk_file_key_wrappings_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

    recipient_type: Mapped[str] = mapped_column(
        Enum("USER", "RECOVERY", name="file_key_recipient_type_enum"),
        nullable=False,
    )

    recipient_user_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_file_key_wrappings_recipient_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )
    user_key_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        nullable=True,
    )
    recovery_key_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "recovery_keys.id",
            name="fk_file_key_wrappings_recovery_key",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )

    wrapped_file_key: Mapped[bytes] = mapped_column(mysql.VARBINARY(1024), nullable=False)
    wrapping_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="RSA-OAEP-SHA256", server_default="RSA-OAEP-SHA256"
    )

    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "REVOKED", name="file_key_wrapping_status_enum"),
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

    file = relationship("File", back_populates="key_wrappings")
    recipient_user = relationship(
        "User",
        back_populates="key_wrappings",
        foreign_keys=[recipient_user_id],
        overlaps="file_key_wrappings,user_key",
    )
    user_key = relationship(
        "UserKey",
        back_populates="file_key_wrappings",
        foreign_keys=[user_key_id, recipient_user_id],
        overlaps="key_wrappings,recipient_user",
    )
    recovery_key = relationship("RecoveryKey", back_populates="file_key_wrappings")
