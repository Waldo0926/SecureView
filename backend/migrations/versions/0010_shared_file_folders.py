"""Let recipients file shared files into their own folders.

Revision ID: 0010_shared_file_folders
Revises: 0009_more_aead_suites
Create Date: 2026-10-02

Folders were only for files you own: placement lived in `files.folder_id`, which belongs to the
owner, so a file someone shared with you could never be put in a folder of yours. With many
people sharing with one account, the "Shared with me" list had no way to be organised.

A recipient's placement is theirs alone, so it lives on their own access grant:
`file_access_grants.folder_id`, pointing at one of their folders. The owner's placement stays in
`files.folder_id`, unchanged, so no existing row moves. Deleting a folder sets the column to
NULL (the files are then in no folder), exactly as it already does for `files.folder_id`.
Adding a nullable column is all this needs, so existing rows are untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0010_shared_file_folders"
down_revision: str | Sequence[str] | None = "0009_more_aead_suites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_marker(value: str) -> None:
    op.execute(
        sa.text(f"ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision SET DEFAULT '{value}'")
    )
    op.execute(sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{value}' WHERE id = 1"))


def upgrade() -> None:
    op.add_column(
        "file_access_grants",
        sa.Column("folder_id", mysql.BIGINT(unsigned=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_file_access_grants_folder",
        "file_access_grants",
        "file_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
        onupdate="CASCADE",
    )
    op.create_index("idx_file_access_grants_folder_id", "file_access_grants", ["folder_id"])
    # The readiness marker goes last, so a failure part-way never advertises this schema.
    _set_marker(revision)


def downgrade() -> None:
    # Dropping the column only forgets where recipients filed shared files; no file, key or
    # access is lost, so there is nothing to refuse.
    _set_marker(str(down_revision))
    op.drop_index("idx_file_access_grants_folder_id", table_name="file_access_grants")
    op.drop_constraint("fk_file_access_grants_folder", "file_access_grants", type_="foreignkey")
    op.drop_column("file_access_grants", "folder_id")
