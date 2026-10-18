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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.enums import VerificationCodeStatus, VerificationPurpose


class EmailVerificationCode(Base):
    """One issued email challenge. Only a keyed digest of the code is stored."""

    __tablename__ = "email_verification_codes"
    __table_args__ = (
        UniqueConstraint("code_uuid", name="uq_email_verification_codes_code_uuid"),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_email_verification_codes_expiry_after_creation",
        ),
        CheckConstraint(
            "max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_email_verification_codes_attempts",
        ),
        CheckConstraint(
            "(status = 'CONSUMED' AND consumed_at IS NOT NULL) OR "
            "(status <> 'CONSUMED' AND consumed_at IS NULL)",
            name="ck_email_verification_codes_consumed_at",
        ),
        Index(
            "idx_email_verification_codes_lookup",
            "email",
            "purpose",
            "status",
            "expires_at",
        ),
        Index("idx_email_verification_codes_user_id", "user_id"),
        Index("idx_email_verification_codes_expires_at", "expires_at"),
        Index("idx_email_verification_codes_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    code_uuid: Mapped[str] = mapped_column(
        CHAR(36),
        nullable=False,
        default=lambda: str(uuid4()),
    )

    purpose: Mapped[VerificationPurpose] = mapped_column(
        Enum(VerificationPurpose, name="email_verification_purpose_enum"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Present only for password reset, where the challenge binds to a known account.
    user_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_email_verification_codes_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    code_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    status: Mapped[VerificationCodeStatus] = mapped_column(
        Enum(VerificationCodeStatus, name="email_verification_code_status_enum"),
        nullable=False,
        default=VerificationCodeStatus.PENDING,
        server_default=VerificationCodeStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        default=5,
        server_default="5",
    )

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
