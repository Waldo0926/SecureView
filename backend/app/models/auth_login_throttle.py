from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, Enum, Index, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.enums import LoginThrottleScope


class AuthLoginThrottle(Base):
    __tablename__ = "auth_login_throttles"
    __table_args__ = (
        Index("idx_auth_login_throttles_blocked_until", "blocked_until"),
        Index("idx_auth_login_throttles_updated_at", "updated_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    scope: Mapped[LoginThrottleScope] = mapped_column(
        Enum(LoginThrottleScope, name="auth_login_throttle_scope_enum"),
        primary_key=True,
    )
    key_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        nullable=False,
        default=0,
        server_default="0",
    )
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
    )
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )
