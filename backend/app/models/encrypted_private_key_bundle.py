from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EncryptedPrivateKeyBundle(Base):
    """A client-encrypted PKCS#8 private key; plaintext key material never persists."""

    __tablename__ = "encrypted_private_key_bundles"
    __table_args__ = (
        UniqueConstraint("bundle_uuid", name="uq_encrypted_private_key_bundles_uuid"),
        UniqueConstraint("user_key_id", name="uq_encrypted_private_key_bundles_user_key"),
        ForeignKeyConstraint(
            ["user_key_id", "user_id"],
            ["user_keys.id", "user_keys.user_id"],
            name="fk_encrypted_private_key_bundles_user_key_owner",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        Index("idx_encrypted_private_key_bundles_user_id", "user_id"),
        Index(
            "idx_encrypted_private_key_bundles_user_key_owner",
            "user_key_id",
            "user_id",
        ),
        CheckConstraint(
            "format_version >= 1 AND aad_version >= 1 AND revision >= 1",
            name="ck_encrypted_private_key_bundles_versions",
        ),
        CheckConstraint(
            "private_key_format = 'PKCS8-DER' "
            "AND derivation_algorithm = 'HKDF-SHA256' "
            "AND encryption_algorithm = 'AES-256-GCM'",
            name="ck_encrypted_private_key_bundles_crypto_suite",
        ),
        CheckConstraint(
            "OCTET_LENGTH(derivation_salt) BETWEEN 16 AND 32 "
            "AND OCTET_LENGTH(nonce) = 12 "
            "AND OCTET_LENGTH(auth_tag) = 16 "
            "AND OCTET_LENGTH(encrypted_private_key) BETWEEN 1 AND 16384",
            name="ck_encrypted_private_key_bundles_envelope",
        ),
        CheckConstraint(
            "ciphertext_sha256 REGEXP '^[0-9a-f]{64}$'",
            name="ck_encrypted_private_key_bundles_sha256",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    bundle_uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "user_key_protection_profiles.user_id",
            name="fk_encrypted_private_key_bundles_profile",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    user_key_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)

    format_version: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=1, server_default="1"
    )
    private_key_format: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PKCS8-DER", server_default="PKCS8-DER"
    )
    derivation_algorithm: Mapped[str] = mapped_column(
        String(30), nullable=False, default="HKDF-SHA256", server_default="HKDF-SHA256"
    )
    derivation_salt: Mapped[bytes] = mapped_column(mysql.VARBINARY(32), nullable=False)
    encryption_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="AES-256-GCM", server_default="AES-256-GCM"
    )
    encrypted_private_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(mysql.VARBINARY(32), nullable=False)
    auth_tag: Mapped[bytes] = mapped_column(mysql.VARBINARY(32), nullable=False)
    aad_version: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=1, server_default="1"
    )
    ciphertext_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    revision: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=1, server_default="1"
    )

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=text("CURRENT_TIMESTAMP(6)"),
    )

    user_key = relationship(
        "UserKey",
        back_populates="encrypted_private_key_bundle",
        foreign_keys=[user_key_id],
        overlaps="protection_profile",
    )
    protection_profile = relationship(
        "UserKeyProtectionProfile",
        back_populates="encrypted_private_key_bundles",
        foreign_keys=[user_id],
        overlaps="encrypted_private_key_bundle,user_key",
    )
