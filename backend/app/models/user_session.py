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
    func,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.enums import SessionStatus


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("session_uuid", name="uq_user_sessions_session_uuid"),
        UniqueConstraint("access_token_hash", name="uq_user_sessions_access_token_hash"),
        CheckConstraint(
            "access_expires_at <= absolute_expires_at",
            name="ck_user_sessions_access_before_absolute",
        ),
        Index("idx_user_sessions_user_status", "user_id", "status"),
        Index(
            "idx_user_sessions_status_access_expires",
            "status",
            "access_expires_at",
        ),
        Index(
            "idx_user_sessions_status_absolute_expires",
            "status",
            "absolute_expires_at",
        ),
        Index("idx_user_sessions_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(
        CHAR(36),
        nullable=False,
        default=lambda: str(uuid4()),
    )

    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_user_sessions_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    access_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="user_session_status_enum"),
        nullable=False,
        default=SessionStatus.ACTIVE,
        server_default=SessionStatus.ACTIVE.value,
    )

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )
    access_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user = relationship("User", back_populates="sessions")
    refresh_tokens = relationship(
        "SessionRefreshToken",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionRefreshToken.generation",
    )
