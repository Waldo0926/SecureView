from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_actor_user_id", "actor_user_id"),
        Index("idx_audit_logs_target_user_id", "target_user_id"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_resource", "resource_type", "resource_id"),
        Index(
            "idx_audit_logs_resource_created_id",
            "resource_type",
            "resource_id",
            "created_at",
            "id",
        ),
        Index("idx_audit_logs_result", "result"),
        Index("idx_audit_logs_created_at", "created_at"),
        Index("idx_audit_logs_created_id", "created_at", "id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)

    actor_user_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_audit_logs_actor_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(
        Enum(
            "AUTH",
            "USER",
            "FILE",
            "SHARE",
            "RECOVERY",
            "INTEGRITY",
            "SYSTEM",
            name="audit_resource_type_enum",
        ),
        nullable=False,
    )
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    target_user_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_audit_logs_target_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )

    result: Mapped[str] = mapped_column(
        Enum("SUCCESS", "FAIL", name="audit_result_enum"),
        nullable=False,
    )

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    previous_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    current_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )

    actor_user = relationship("User", back_populates="audit_logs", foreign_keys=[actor_user_id])
    target_user = relationship(
        "User", back_populates="targeted_audit_logs", foreign_keys=[target_user_id]
    )
