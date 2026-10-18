from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RecoveryKey(Base):
    __tablename__ = "recovery_keys"
    __table_args__ = (
        UniqueConstraint("key_uuid", name="uq_recovery_keys_key_uuid"),
        UniqueConstraint("fingerprint", name="uq_recovery_keys_fingerprint"),
        CheckConstraint(
            "key_size_bits IN (2048, 3072, 4096)",
            name="ck_recovery_keys_supported_size",
        ),
        CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="ck_recovery_keys_status_revoked_at",
        ),
        Index("idx_recovery_keys_status", "status"),
        Index("idx_recovery_keys_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    key_uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False, default=lambda: str(uuid4()))

    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="RSA-OAEP-SHA256", server_default="RSA-OAEP-SHA256"
    )
    key_size_bits: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True),
        nullable=False,
        default=3072,
        server_default="3072",
    )
    fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "REVOKED", name="recovery_key_status_enum"),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    file_key_wrappings = relationship("FileKeyWrapping", back_populates="recovery_key")
