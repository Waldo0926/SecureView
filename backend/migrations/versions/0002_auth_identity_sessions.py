"""Add public identity, rotating sessions, throttling, and an audit chain head.

Revision ID: 0002_auth_identity_sessions
Revises: 0001_initial
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002_auth_identity_sessions"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}
GENESIS_AUDIT_HASH = "0" * 64


def upgrade() -> None:
    # Revision 0001 used a different canonical hash payload and DATETIME(0), so
    # a non-empty historical chain cannot be losslessly verified or converted.
    # Refuse before any permanent schema change and require a reviewed adoption
    # migration with an externally recorded checkpoint instead of pretending
    # that two incompatible hash formats form one verifiable chain.
    op.execute(sa.text("DROP TEMPORARY TABLE IF EXISTS auth_0002_audit_upgrade_guard"))
    op.execute(
        sa.text(
            "CREATE TEMPORARY TABLE auth_0002_audit_upgrade_guard ("
            "empty_legacy_chain TINYINT NOT NULL, "
            "CONSTRAINT ck_auth_0002_requires_empty_audit_log "
            "CHECK (empty_legacy_chain = 1)"
            ") ENGINE=InnoDB"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO auth_0002_audit_upgrade_guard (empty_legacy_chain) "
            "SELECT 0 FROM audit_logs LIMIT 1"
        )
    )
    op.execute(sa.text("DROP TEMPORARY TABLE auth_0002_audit_upgrade_guard"))

    # Add public user identities without making existing rows violate NOT NULL or
    # uniqueness. UUID() is evaluated once per row by MySQL.
    op.add_column("users", sa.Column("user_uuid", sa.CHAR(length=36), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.execute(sa.text("UPDATE users SET user_uuid = UUID() WHERE user_uuid IS NULL"))
    op.execute(
        sa.text(
            "UPDATE users "
            "SET password_changed_at = COALESCE(updated_at, created_at, UTC_TIMESTAMP()) "
            "WHERE password_changed_at IS NULL"
        )
    )
    op.alter_column(
        "users",
        "user_uuid",
        existing_type=sa.CHAR(length=36),
        nullable=False,
    )
    op.alter_column(
        "users",
        "password_changed_at",
        existing_type=sa.DateTime(),
        existing_server_default=sa.func.now(),
        nullable=False,
    )
    op.create_unique_constraint("uq_users_user_uuid", "users", ["user_uuid"])

    # Replace the original single opaque session credential with a short-lived
    # access credential plus an absolute session boundary.
    op.drop_constraint(
        "uq_user_sessions_token_hash",
        "user_sessions",
        type_="unique",
    )
    # MySQL requires an index whose first column is user_id for the existing
    # fk_user_sessions_user foreign key. Create the replacement composite index
    # before removing the legacy single-column index so the constraint remains
    # backed throughout this non-transactional DDL sequence.
    op.create_index(
        "idx_user_sessions_user_status",
        "user_sessions",
        ["user_id", "status"],
        unique=False,
    )
    op.drop_index("idx_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("idx_user_sessions_status", table_name="user_sessions")
    op.drop_index("idx_user_sessions_expires_at", table_name="user_sessions")
    op.alter_column(
        "user_sessions",
        "session_token_hash",
        new_column_name="access_token_hash",
        existing_type=sa.CHAR(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "user_sessions",
        "expires_at",
        new_column_name="access_expires_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
    )
    op.add_column(
        "user_sessions",
        sa.Column("session_uuid", sa.CHAR(length=36), nullable=True),
    )
    op.add_column(
        "user_sessions",
        sa.Column("absolute_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "user_sessions",
        sa.Column("revoked_reason", sa.String(length=100), nullable=True),
    )
    op.execute(sa.text("UPDATE user_sessions SET session_uuid = UUID() WHERE session_uuid IS NULL"))
    op.execute(
        sa.text(
            "UPDATE user_sessions "
            "SET absolute_expires_at = access_expires_at "
            "WHERE absolute_expires_at IS NULL"
        )
    )
    op.alter_column(
        "user_sessions",
        "session_uuid",
        existing_type=sa.CHAR(length=36),
        nullable=False,
    )
    op.alter_column(
        "user_sessions",
        "absolute_expires_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_user_sessions_session_uuid",
        "user_sessions",
        ["session_uuid"],
    )
    op.create_unique_constraint(
        "uq_user_sessions_access_token_hash",
        "user_sessions",
        ["access_token_hash"],
    )
    op.create_check_constraint(
        "ck_user_sessions_access_before_absolute",
        "user_sessions",
        "access_expires_at <= absolute_expires_at",
    )
    op.create_index(
        "idx_user_sessions_status_access_expires",
        "user_sessions",
        ["status", "access_expires_at"],
        unique=False,
    )
    op.create_index(
        "idx_user_sessions_status_absolute_expires",
        "user_sessions",
        ["status", "absolute_expires_at"],
        unique=False,
    )

    op.create_table(
        "session_refresh_tokens",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("generation", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_session_refresh_tokens_expiry_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            name="fk_session_refresh_tokens_session",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_session_refresh_tokens_token_hash"),
        sa.UniqueConstraint(
            "session_id",
            "generation",
            name="uq_session_refresh_tokens_session_generation",
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_session_refresh_tokens_expires_at",
        "session_refresh_tokens",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "auth_login_throttles",
        sa.Column(
            "scope",
            sa.Enum(
                "ACCOUNT",
                "IP",
                "REAUTH_ACCOUNT",
                "REAUTH_IP",
                "REGISTRATION_IP",
                name="auth_login_throttle_scope_enum",
            ),
            nullable=False,
        ),
        sa.Column("key_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "failed_count",
            mysql.INTEGER(unsigned=True),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "window_started_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("blocked_until", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scope", "key_hash"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_auth_login_throttles_blocked_until",
        "auth_login_throttles",
        ["blocked_until"],
        unique=False,
    )
    op.create_index(
        "idx_auth_login_throttles_updated_at",
        "auth_login_throttles",
        ["updated_at"],
        unique=False,
    )

    # Actor/target IDs are part of the tamper-evident payload. Cascading an ID
    # update or nulling it on hard delete would mutate a historical row without
    # updating its hash, so the database must enforce soft deletion of users.
    op.drop_constraint("fk_audit_logs_actor_user", "audit_logs", type_="foreignkey")
    op.drop_constraint("fk_audit_logs_target_user", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "fk_audit_logs_actor_user",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_audit_logs_target_user",
        "audit_logs",
        "users",
        ["target_user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    # The hash payload must exactly match the values MySQL returns. Normalize
    # the previous nullable representation and retain all six Python datetime
    # microsecond digits before new chained entries can be appended.
    op.execute(
        sa.text(
            "UPDATE audit_logs SET metadata_json = JSON_OBJECT() "
            "WHERE metadata_json IS NULL OR JSON_TYPE(metadata_json) = 'NULL'"
        )
    )
    op.alter_column(
        "audit_logs",
        "metadata_json",
        existing_type=sa.JSON(),
        nullable=False,
    )
    op.alter_column(
        "audit_logs",
        "created_at",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    op.create_table(
        "audit_chain_heads",
        sa.Column(
            "id",
            mysql.TINYINT(unsigned=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("last_log_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("current_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_audit_chain_heads_singleton"),
        sa.ForeignKeyConstraint(
            ["last_log_id"],
            ["audit_logs.id"],
            name="fk_audit_chain_heads_last_log",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    # The precondition above guarantees a genuinely empty, verifiable chain.
    op.execute(
        sa.text(
            "INSERT INTO audit_chain_heads (id, last_log_id, current_hash) "
            f"VALUES (1, NULL, '{GENESIS_AUDIT_HASH}')"
        )
    )


def downgrade() -> None:
    # Public user/session UUIDs, refresh generations, throttle evidence, and
    # Argon2 password upgrades cannot be represented safely by revision 0001.
    # This revision is intentionally forward-only; disposable development
    # databases must be rebuilt rather than assigned different public identities.
    op.execute(
        sa.text(
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
            "'0002_auth_identity_sessions is irreversible; restore a backup or rebuild'"
        )
    )

    op.drop_table("audit_chain_heads")

    op.alter_column(
        "audit_logs",
        "created_at",
        existing_type=mysql.DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "audit_logs",
        "metadata_json",
        existing_type=sa.JSON(),
        nullable=True,
    )
    op.drop_constraint("fk_audit_logs_target_user", "audit_logs", type_="foreignkey")
    op.drop_constraint("fk_audit_logs_actor_user", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "fk_audit_logs_actor_user",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "fk_audit_logs_target_user",
        "audit_logs",
        "users",
        ["target_user_id"],
        ["id"],
        ondelete="SET NULL",
        onupdate="CASCADE",
    )

    op.drop_index(
        "idx_auth_login_throttles_updated_at",
        table_name="auth_login_throttles",
    )
    op.drop_index(
        "idx_auth_login_throttles_blocked_until",
        table_name="auth_login_throttles",
    )
    op.drop_table("auth_login_throttles")

    op.drop_index(
        "idx_session_refresh_tokens_expires_at",
        table_name="session_refresh_tokens",
    )
    op.drop_table("session_refresh_tokens")

    op.drop_index(
        "idx_user_sessions_status_absolute_expires",
        table_name="user_sessions",
    )
    op.drop_index(
        "idx_user_sessions_status_access_expires",
        table_name="user_sessions",
    )
    op.drop_index("idx_user_sessions_user_status", table_name="user_sessions")
    op.drop_constraint(
        "ck_user_sessions_access_before_absolute",
        "user_sessions",
        type_="check",
    )
    op.drop_constraint(
        "uq_user_sessions_access_token_hash",
        "user_sessions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_user_sessions_session_uuid",
        "user_sessions",
        type_="unique",
    )
    op.drop_column("user_sessions", "revoked_reason")
    op.drop_column("user_sessions", "absolute_expires_at")
    op.drop_column("user_sessions", "session_uuid")
    op.alter_column(
        "user_sessions",
        "access_token_hash",
        new_column_name="session_token_hash",
        existing_type=sa.CHAR(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "user_sessions",
        "access_expires_at",
        new_column_name="expires_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_user_sessions_token_hash",
        "user_sessions",
        ["session_token_hash"],
    )
    op.create_index(
        "idx_user_sessions_user_id",
        "user_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_user_sessions_status",
        "user_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_user_sessions_expires_at",
        "user_sessions",
        ["expires_at"],
        unique=False,
    )

    op.drop_constraint("uq_users_user_uuid", "users", type_="unique")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "user_uuid")
