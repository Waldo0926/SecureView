from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserKey(Base):
    __tablename__ = "user_keys"
    __table_args__ = (
        UniqueConstraint("key_uuid", name="uq_user_keys_key_uuid"),
        UniqueConstraint("fingerprint", name="uq_user_keys_fingerprint"),
        UniqueConstraint("id", "user_id", name="uq_user_keys_id_user_id"),
        CheckConstraint(
            "key_size_bits IN (2048, 3072, 4096)",
            name="ck_user_keys_supported_size",
        ),
        CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="ck_user_keys_status_revoked_at",
        ),
        Index("idx_user_keys_user_id", "user_id"),
        Index("idx_user_keys_user_status", "user_id", "status"),
        Index("idx_user_keys_status", "status"),
        Index("idx_user_keys_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )

    key_uuid: Mapped[str] = mapped_column(
        CHAR(36),
        nullable=False,
        default=lambda: str(uuid4()),
    )

    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_user_keys_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

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

    custody_mode: Mapped[str] = mapped_column(
        Enum(
            "LEGACY_EXTERNAL",
            "CLIENT_WRAPPED",
            name="user_key_custody_mode_enum",
        ),
        nullable=False,
        default="LEGACY_EXTERNAL",
        server_default="LEGACY_EXTERNAL",
    )

    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "REVOKED", name="user_key_status_enum"),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="keys")
    file_key_wrappings = relationship(
        "FileKeyWrapping",
        back_populates="user_key",
        overlaps="key_wrappings,recipient_user",
    )
    encrypted_private_key_bundle = relationship(
        "EncryptedPrivateKeyBundle",
        back_populates="user_key",
        uselist=False,
        cascade="all, delete-orphan",
        overlaps="protection_profile",
    )
