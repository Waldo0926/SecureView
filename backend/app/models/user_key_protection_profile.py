from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserKeyProtectionProfile(Base):
    """Account-level parameters and ciphertext used to unlock the account master key."""

    __tablename__ = "user_key_protection_profiles"
    __table_args__ = (
        UniqueConstraint("profile_uuid", name="uq_user_key_protection_profiles_uuid"),
        CheckConstraint(
            "format_version >= 1 AND aad_version >= 1 AND revision >= 1",
            name="ck_user_key_protection_profiles_versions",
        ),
        CheckConstraint(
            "kdf_algorithm = 'ARGON2ID' AND kdf_version = 19 AND derived_key_length = 32",
            name="ck_user_key_protection_profiles_kdf_suite",
        ),
        CheckConstraint(
            "kdf_memory_kib BETWEEN 65536 AND 1048576 "
            "AND kdf_iterations BETWEEN 1 AND 20 "
            "AND kdf_parallelism BETWEEN 1 AND 16",
            name="ck_user_key_protection_profiles_kdf_bounds",
        ),
        CheckConstraint(
            "OCTET_LENGTH(kdf_salt) BETWEEN 16 AND 32",
            name="ck_user_key_protection_profiles_salt_length",
        ),
        CheckConstraint(
            "amk_wrapping_algorithm = 'AES-256-GCM' "
            "AND OCTET_LENGTH(wrapped_amk) = 32 "
            "AND OCTET_LENGTH(amk_nonce) = 12 "
            "AND OCTET_LENGTH(amk_auth_tag) = 16",
            name="ck_user_key_protection_profiles_amk_envelope",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_user_key_protection_profiles_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
        autoincrement=False,
    )
    profile_uuid: Mapped[str] = mapped_column(
        CHAR(36), nullable=False, default=lambda: str(uuid4())
    )

    format_version: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=1, server_default="1"
    )
    kdf_algorithm: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ARGON2ID", server_default="ARGON2ID"
    )
    kdf_version: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=19, server_default="19"
    )
    kdf_salt: Mapped[bytes] = mapped_column(mysql.VARBINARY(32), nullable=False)
    kdf_memory_kib: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    kdf_iterations: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True), nullable=False)
    kdf_parallelism: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True), nullable=False)
    derived_key_length: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=32, server_default="32"
    )

    amk_wrapping_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="AES-256-GCM", server_default="AES-256-GCM"
    )
    wrapped_amk: Mapped[bytes] = mapped_column(mysql.VARBINARY(64), nullable=False)
    amk_nonce: Mapped[bytes] = mapped_column(mysql.VARBINARY(32), nullable=False)
    amk_auth_tag: Mapped[bytes] = mapped_column(mysql.VARBINARY(32), nullable=False)
    aad_version: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), nullable=False, default=1, server_default="1"
    )
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

    user = relationship("User", back_populates="key_protection_profile")
    encrypted_private_key_bundles = relationship(
        "EncryptedPrivateKeyBundle",
        back_populates="protection_profile",
        cascade="all, delete-orphan",
        overlaps="encrypted_private_key_bundle,user_key",
    )
