from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RecoveryRequest(Base):
    __tablename__ = "recovery_requests"
    __table_args__ = (
        UniqueConstraint("request_uuid", name="uq_recovery_requests_request_uuid"),
        ForeignKeyConstraint(
            ["target_user_key_id", "requested_by"],
            ["user_keys.id", "user_keys.user_id"],
            name="fk_recovery_requests_target_key_owner",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_recovery_requests_expiry_after_creation",
        ),
        CheckConstraint(
            "approved_by IS NULL OR approved_by <> requested_by",
            name="ck_recovery_requests_maker_checker",
        ),
        CheckConstraint("revision >= 1", name="ck_recovery_requests_revision"),
        CheckConstraint(
            "(status = 'PENDING' "
            "AND approved_at IS NULL AND rejected_at IS NULL "
            "AND executed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'APPROVED' "
            "AND approved_at IS NOT NULL AND rejected_at IS NULL "
            "AND executed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'REJECTED' "
            "AND approved_at IS NULL AND rejected_at IS NOT NULL "
            "AND executed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'EXECUTED' "
            "AND approved_at IS NOT NULL AND rejected_at IS NULL "
            "AND executed_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'CANCELLED' "
            "AND approved_at IS NULL AND rejected_at IS NULL "
            "AND executed_at IS NULL AND cancelled_at IS NOT NULL)",
            name="ck_recovery_requests_status_timestamps",
        ),
        CheckConstraint(
            "result_wrapping_id IS NULL OR status = 'EXECUTED'",
            name="ck_recovery_requests_result_status",
        ),
        Index("idx_recovery_requests_file_id", "file_id"),
        Index("idx_recovery_requests_requested_by", "requested_by"),
        Index("idx_recovery_requests_approved_by", "approved_by"),
        Index("idx_recovery_requests_executed_by", "executed_by"),
        Index("idx_recovery_requests_status", "status"),
        Index("idx_recovery_requests_status_created", "status", "created_at", "id"),
        Index("idx_recovery_requests_target_user_key_id", "target_user_key_id"),
        Index(
            "idx_recovery_requests_target_key_owner",
            "target_user_key_id",
            "requested_by",
        ),
        Index("idx_recovery_requests_result_wrapping_id", "result_wrapping_id"),
        Index("idx_recovery_requests_created_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )

    request_uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False)

    file_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "files.id",
            name="fk_recovery_requests_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

    requested_by: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_recovery_requests_requested_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    approved_by: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_recovery_requests_approved_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )
    executed_by: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "users.id",
            name="fk_recovery_requests_executed_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )
    target_user_key_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), nullable=True
    )
    result_wrapping_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "file_key_wrappings.id",
            name="fk_recovery_requests_result_wrapping",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(
            "PENDING",
            "APPROVED",
            "REJECTED",
            "EXECUTED",
            "CANCELLED",
            name="recovery_request_status_enum",
        ),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), nullable=False, default=1, server_default="1"
    )

    file = relationship("File", back_populates="recovery_requests")
    requester = relationship(
        "User", back_populates="requested_recovery_requests", foreign_keys=[requested_by]
    )
    approver = relationship(
        "User", back_populates="approved_recovery_requests", foreign_keys=[approved_by]
    )
    executor = relationship(
        "User", back_populates="executed_recovery_requests", foreign_keys=[executed_by]
    )
    target_user_key = relationship("UserKey", foreign_keys=[target_user_key_id])
    result_wrapping = relationship("FileKeyWrapping", foreign_keys=[result_wrapping_id])
