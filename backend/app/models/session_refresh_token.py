from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SessionRefreshToken(Base):
    __tablename__ = "session_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_session_refresh_tokens_token_hash"),
        UniqueConstraint(
            "session_id",
            "generation",
            name="uq_session_refresh_tokens_session_generation",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_session_refresh_tokens_expiry_after_creation",
        ),
        Index("idx_session_refresh_tokens_expires_at", "expires_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "user_sessions.id",
            name="fk_session_refresh_tokens_session",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    generation: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session = relationship("UserSession", back_populates="refresh_tokens")
