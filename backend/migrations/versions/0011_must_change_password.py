"""Mark an account whose login password an administrator reset.

Revision ID: 0011_must_change_password
Revises: 0010_shared_file_folders
Create Date: 2026-10-09

`POST /admin/users/{user_id}/reset-password` gives an account a random temporary password,
signs it out everywhere and emails the holder. Nothing recorded that this had happened, so
the holder could keep using the temporary password, which the administrator has seen and
which travelled by hand, for as long as they liked.

`users.must_change_password` is set by that reset and cleared when the holder sets a
password of their own, through `POST /auth/change-password` or the emailed reset. Login and
`GET /auth/me` return it; the frontend sends the holder to Settings while it is true. The
API refuses nothing because of it, so a holder can never be locked out of changing the
password itself. Adding a NOT NULL column with a default is all this needs; existing rows
get FALSE, which is correct for every account that was not reset.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_must_change_password"
down_revision: str | Sequence[str] | None = "0010_shared_file_folders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_marker(value: str) -> None:
    op.execute(
        sa.text(f"ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision SET DEFAULT '{value}'")
    )
    op.execute(sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{value}' WHERE id = 1"))


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # The readiness marker goes last, so a failure part-way never advertises this schema.
    _set_marker(revision)


def downgrade() -> None:
    # Dropping the column only forgets which accounts still hold a temporary password; no
    # password, key or file is lost, so there is nothing to refuse.
    _set_marker(str(down_revision))
    op.drop_column("users", "must_change_password")
