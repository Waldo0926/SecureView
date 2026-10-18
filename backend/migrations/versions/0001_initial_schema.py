"""Create the initial application schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("USER", "ADMIN", "RECOVERY_OFFICER", name="user_role_enum"),
            server_default="USER",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DISABLED", "DELETED", name="user_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("email_verified", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        **TABLE_OPTIONS,
    )
    op.create_index("idx_users_created_at", "users", ["created_at"], unique=False)
    op.create_index("idx_users_role", "users", ["role"], unique=False)
    op.create_index("idx_users_status", "users", ["status"], unique=False)

    op.create_table(
        "recovery_keys",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column(
            "algorithm",
            sa.String(length=50),
            server_default="RSA-OAEP-SHA256",
            nullable=False,
        ),
        sa.Column("fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="recovery_key_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_recovery_keys_fingerprint"),
        **TABLE_OPTIONS,
    )
    op.create_index("idx_recovery_keys_created_at", "recovery_keys", ["created_at"], unique=False)
    op.create_index("idx_recovery_keys_status", "recovery_keys", ["status"], unique=False)

    op.create_table(
        "user_keys",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column(
            "algorithm",
            sa.String(length=50),
            server_default="RSA-OAEP-SHA256",
            nullable=False,
        ),
        sa.Column("fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="user_key_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_keys_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_user_keys_fingerprint"),
        **TABLE_OPTIONS,
    )
    op.create_index("idx_user_keys_created_at", "user_keys", ["created_at"], unique=False)
    op.create_index("idx_user_keys_status", "user_keys", ["status"], unique=False)
    op.create_index("idx_user_keys_user_id", "user_keys", ["user_id"], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("session_token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "EXPIRED", "REVOKED", name="user_session_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_sessions_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_token_hash", name="uq_user_sessions_token_hash"),
        **TABLE_OPTIONS,
    )
    op.create_index("idx_user_sessions_created_at", "user_sessions", ["created_at"], unique=False)
    op.create_index("idx_user_sessions_expires_at", "user_sessions", ["expires_at"], unique=False)
    op.create_index("idx_user_sessions_status", "user_sessions", ["status"], unique=False)
    op.create_index("idx_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)

    op.create_table(
        "files",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("file_uuid", sa.CHAR(length=36), nullable=False),
        sa.Column("owner_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_object_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=True),
        sa.Column("file_size_bytes", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("encrypted_size_bytes", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "encryption_algorithm",
            sa.String(length=50),
            server_default="AES-256-GCM",
            nullable=False,
        ),
        sa.Column("iv", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("auth_tag", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("encrypted_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DELETED", "CORRUPTED", name="file_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_files_owner",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_uuid", name="uq_files_file_uuid"),
        sa.UniqueConstraint("stored_filename", name="uq_files_stored_filename"),
        **TABLE_OPTIONS,
    )
    op.create_index("idx_files_created_at", "files", ["created_at"], unique=False)
    op.create_index("idx_files_owner_id", "files", ["owner_id"], unique=False)
    op.create_index("idx_files_status", "files", ["status"], unique=False)

    op.create_table(
        "file_key_wrappings",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("file_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "recipient_type",
            sa.Enum("USER", "RECOVERY", name="file_key_recipient_type_enum"),
            nullable=False,
        ),
        sa.Column("recipient_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("user_key_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("recovery_key_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("wrapped_file_key", mysql.VARBINARY(length=1024), nullable=False),
        sa.Column(
            "wrapping_algorithm",
            sa.String(length=50),
            server_default="RSA-OAEP-SHA256",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="file_key_wrapping_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_file_key_wrappings_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_file_key_wrappings_recipient_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_key_id"],
            ["recovery_keys.id"],
            name="fk_file_key_wrappings_recovery_key",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_key_id"],
            ["user_keys.id"],
            name="fk_file_key_wrappings_user_key",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_file_key_wrappings_created_at",
        "file_key_wrappings",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_file_key_wrappings_file_id",
        "file_key_wrappings",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "idx_file_key_wrappings_recipient_type",
        "file_key_wrappings",
        ["recipient_type"],
        unique=False,
    )
    op.create_index(
        "idx_file_key_wrappings_recipient_user_id",
        "file_key_wrappings",
        ["recipient_user_id"],
        unique=False,
    )
    op.create_index(
        "idx_file_key_wrappings_recovery_key_id",
        "file_key_wrappings",
        ["recovery_key_id"],
        unique=False,
    )
    op.create_index(
        "idx_file_key_wrappings_status",
        "file_key_wrappings",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_file_key_wrappings_user_key_id",
        "file_key_wrappings",
        ["user_key_id"],
        unique=False,
    )

    op.create_table(
        "file_access_grants",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("file_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("granted_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("can_download", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("can_share", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("can_revoke", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("can_manage", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="file_access_grant_status_enum"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_file_access_grants_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_file_access_grants_granted_by",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_file_access_grants_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "user_id", name="uq_file_access_grants_file_user"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_file_access_grants_created_at",
        "file_access_grants",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_file_access_grants_file_id",
        "file_access_grants",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "idx_file_access_grants_granted_by",
        "file_access_grants",
        ["granted_by"],
        unique=False,
    )
    op.create_index(
        "idx_file_access_grants_status",
        "file_access_grants",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_file_access_grants_user_id",
        "file_access_grants",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column(
            "resource_type",
            sa.Enum(
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
        ),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("target_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "result",
            sa.Enum("SUCCESS", "FAIL", name="audit_result_enum"),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("previous_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("current_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_logs_actor_user",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_audit_logs_target_user",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    op.create_index("idx_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index(
        "idx_audit_logs_actor_user_id",
        "audit_logs",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "idx_audit_logs_resource",
        "audit_logs",
        ["resource_type", "resource_id"],
        unique=False,
    )
    op.create_index("idx_audit_logs_result", "audit_logs", ["result"], unique=False)
    op.create_index(
        "idx_audit_logs_target_user_id",
        "audit_logs",
        ["target_user_id"],
        unique=False,
    )

    op.create_table(
        "integrity_checks",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("file_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("checked_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("expected_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("actual_hash", sa.CHAR(length=64), nullable=True),
        sa.Column(
            "result",
            sa.Enum("VALID", "MODIFIED", "MISSING", "ERROR", name="integrity_check_result_enum"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["checked_by"],
            ["users.id"],
            name="fk_integrity_checks_checked_by",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_integrity_checks_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_integrity_checks_checked_by",
        "integrity_checks",
        ["checked_by"],
        unique=False,
    )
    op.create_index(
        "idx_integrity_checks_created_at",
        "integrity_checks",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_integrity_checks_file_id",
        "integrity_checks",
        ["file_id"],
        unique=False,
    )
    op.create_index("idx_integrity_checks_result", "integrity_checks", ["result"], unique=False)

    op.create_table(
        "recovery_requests",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("request_uuid", sa.CHAR(length=36), nullable=False),
        sa.Column("file_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("requested_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("approved_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "APPROVED",
                "REJECTED",
                "EXECUTED",
                "CANCELLED",
                name="recovery_request_status_enum",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_recovery_requests_approved_by",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_recovery_requests_file",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name="fk_recovery_requests_requested_by",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_uuid", name="uq_recovery_requests_request_uuid"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_recovery_requests_approved_by",
        "recovery_requests",
        ["approved_by"],
        unique=False,
    )
    op.create_index(
        "idx_recovery_requests_created_at",
        "recovery_requests",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_recovery_requests_file_id",
        "recovery_requests",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "idx_recovery_requests_requested_by",
        "recovery_requests",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        "idx_recovery_requests_status",
        "recovery_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("recovery_requests")
    op.drop_table("integrity_checks")
    op.drop_table("audit_logs")
    op.drop_table("file_access_grants")
    op.drop_table("file_key_wrappings")
    op.drop_table("files")
    op.drop_table("user_sessions")
    op.drop_table("user_keys")
    op.drop_table("recovery_keys")
    op.drop_table("users")
