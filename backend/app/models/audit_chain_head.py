from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AuditChainHead(Base):
    __tablename__ = "audit_chain_heads"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_audit_chain_heads_singleton"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.TINYINT(unsigned=True),
        primary_key=True,
        autoincrement=False,
    )
    last_log_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "audit_logs.id",
            name="fk_audit_chain_heads_last_log",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    current_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    schema_revision: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="0011_must_change_password",
        server_default="0011_must_change_password",
    )
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=text("CURRENT_TIMESTAMP(6)"),
    )

    last_log = relationship("AuditLog", foreign_keys=[last_log_id], uselist=False)
