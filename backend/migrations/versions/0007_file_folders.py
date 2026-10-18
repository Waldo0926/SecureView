"""Add per-user folders for organizing owned encrypted files.

Revision ID: 0007_file_folders
Revises: 0006_chacha20_poly1305
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007_file_folders"
down_revision: str | Sequence[str] | None = "0006_chacha20_poly1305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_folders",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("folder_uuid", sa.CHAR(length=36), nullable=False),
        sa.Column("owner_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_file_folders_owner",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder_uuid", name="uq_file_folders_folder_uuid"),
        sa.UniqueConstraint("owner_id", "name", name="uq_file_folders_owner_name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_file_folders_owner_name", "file_folders", ["owner_id", "name"])
    op.add_column("files", sa.Column("folder_id", mysql.BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(
        "fk_files_folder",
        "files",
        "file_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
        onupdate="CASCADE",
    )
    op.create_index("idx_files_folder_id", "files", ["folder_id"])
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
    op.drop_index("idx_files_folder_id", table_name="files")
    op.drop_constraint("fk_files_folder", "files", type_="foreignkey")
    op.drop_column("files", "folder_id")
    op.drop_index("idx_file_folders_owner_name", table_name="file_folders")
    op.drop_table("file_folders")
