"""Add email verification challenges for registration and password reset.

Revision ID: 0004_email_verification_codes
Revises: 0003_client_key_custody
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0004_email_verification_codes"
down_revision: str | Sequence[str] | None = "0003_client_key_custody"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

THROTTLE_SCOPES = (
    "ACCOUNT",
    "IP",
    "REAUTH_ACCOUNT",
    "REAUTH_IP",
    "REGISTRATION_IP",
    "VERIFICATION_SEND_EMAIL",
    "VERIFICATION_SEND_IP",
    "VERIFICATION_CHECK_EMAIL",
    "VERIFICATION_CHECK_IP",
)


def upgrade() -> None:
    op.create_table(
        "email_verification_codes",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("code_uuid", sa.CHAR(length=36), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "REGISTRATION",
                "PASSWORD_RESET",
                name="email_verification_purpose_enum",
            ),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("code_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CONSUMED",
                "INVALIDATED",
                name="email_verification_code_status_enum",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            mysql.INTEGER(unsigned=True),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            mysql.INTEGER(unsigned=True),
            server_default="5",
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_uuid", name="uq_email_verification_codes_code_uuid"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_email_verification_codes_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_email_verification_codes_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_email_verification_codes_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'CONSUMED' AND consumed_at IS NOT NULL) OR "
            "(status <> 'CONSUMED' AND consumed_at IS NULL)",
            name="ck_email_verification_codes_consumed_at",
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_email_verification_codes_lookup",
        "email_verification_codes",
        ["email", "purpose", "status", "expires_at"],
    )
    op.create_index(
        "idx_email_verification_codes_user_id",
        "email_verification_codes",
        ["user_id"],
    )
    op.create_index(
        "idx_email_verification_codes_expires_at",
        "email_verification_codes",
        ["expires_at"],
    )
    op.create_index(
        "idx_email_verification_codes_created_at",
        "email_verification_codes",
        ["created_at"],
    )

    # Widen the throttle scope enum so verification send/check buckets share the
    # existing rate-limit table instead of introducing a second mechanism.
    scope_values = ", ".join(f"'{scope}'" for scope in THROTTLE_SCOPES)
    op.execute(
        sa.text(
            f"ALTER TABLE auth_login_throttles MODIFY COLUMN scope ENUM({scope_values}) NOT NULL"
        )
    )

    op.execute(
        sa.text(
            "ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision "
            "SET DEFAULT '0004_email_verification_codes'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE audit_chain_heads SET schema_revision = '0004_email_verification_codes' "
            "WHERE id = 1"
        )
    )


def downgrade() -> None:
    # Order matters and MySQL DDL commits between statements. Remove the
    # dependent table first: DROP TABLE also removes its indexes and the
    # foreign key, whereas dropping the FK-backing index on its own is refused.
    # Only then narrow the shared enum and lower the readiness marker, so a
    # failure never leaves the marker below a schema that still has 0004
    # structures.
    op.drop_table("email_verification_codes")

    legacy_scopes = ", ".join(f"'{scope}'" for scope in THROTTLE_SCOPES[:5])
    op.execute(
        sa.text(
            "DELETE FROM auth_login_throttles WHERE scope IN ("
            "'VERIFICATION_SEND_EMAIL', 'VERIFICATION_SEND_IP', "
            "'VERIFICATION_CHECK_EMAIL', 'VERIFICATION_CHECK_IP')"
        )
    )
    op.execute(
        sa.text(
            f"ALTER TABLE auth_login_throttles MODIFY COLUMN scope ENUM({legacy_scopes}) NOT NULL"
        )
    )

    op.execute(
        sa.text(
            "ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision "
            "SET DEFAULT '0003_client_key_custody'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE audit_chain_heads SET schema_revision = '0003_client_key_custody' WHERE id = 1"
        )
    )
