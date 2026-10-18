"""Add optional validated user avatars.

Revision ID: 0008_avatars
Revises: 0007_file_folders
Create Date: 2026-09-27

Avatars are optional profile images stored as plaintext under a dedicated root outside the
encrypted-object directory. Metadata lives on `users`; bytes are only on disk.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0008_avatars"
down_revision: str | Sequence[str] | None = "0007_file_folders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_object_key", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("avatar_content_type", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("avatar_sha256", sa.CHAR(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("avatar_bytes", mysql.INTEGER(unsigned=True), nullable=True),
    )
    op.add_column("users", sa.Column("avatar_updated_at", sa.DateTime(), nullable=True))
    op.create_check_constraint(
        "ck_users_avatar_shape",
        "users",
        "(avatar_object_key IS NULL AND avatar_content_type IS NULL "
        "AND avatar_sha256 IS NULL AND avatar_bytes IS NULL AND avatar_updated_at IS NULL) "
        "OR (avatar_object_key IS NOT NULL AND avatar_content_type IN ('image/png', 'image/jpeg') "
        "AND avatar_sha256 REGEXP '^[0-9a-f]{64}$' AND avatar_bytes BETWEEN 1 AND 524288 "
        "AND avatar_updated_at IS NOT NULL)",
    )

    op.execute(
        sa.text(
            f"ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision SET DEFAULT '{revision}'"
        )
    )
    op.execute(sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{revision}' WHERE id = 1"))


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision "
            f"SET DEFAULT '{down_revision}'"
        )
    )
    op.execute(
        sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{down_revision}' WHERE id = 1")
    )
    op.drop_constraint("ck_users_avatar_shape", "users", type_="check")
    op.drop_column("users", "avatar_updated_at")
    op.drop_column("users", "avatar_bytes")
    op.drop_column("users", "avatar_sha256")
    op.drop_column("users", "avatar_content_type")
    op.drop_column("users", "avatar_object_key")
