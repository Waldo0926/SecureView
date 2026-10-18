"""Allow AES-128 and AES-192 alongside AES-256 for file content.

Revision ID: 0005_selectable_aes_key_length
Revises: 0004_email_verification_codes
Create Date: 2026-08-26

Only the file content algorithm widens. The account key envelope -- the wrapped AMK and the
encrypted private-key bundle -- stays AES-256-GCM, and its CHECK constraints are untouched:
those envelopes carry no algorithm choice of their own, so there is nothing for a user to
select and no name recorded that a reader could disagree with.

The three names share a 12-byte nonce and a 16-byte tag, so the length half of the constraint
is unchanged. Widening is safe for existing rows because every one of them holds
'AES-256-GCM', which remains legal.

Downgrading is only possible while no AES-128 or AES-192 file exists. Rather than delete
those rows -- which would destroy files that are perfectly intact -- the downgrade refuses,
and says what to do about it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_selectable_aes_key_length"
down_revision: str | Sequence[str] | None = "0004_email_verification_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_files_encryption_envelope"
LENGTHS = "OCTET_LENGTH(iv) = 12 AND OCTET_LENGTH(auth_tag) = 16"
WIDENED = f"encryption_algorithm IN ('AES-128-GCM', 'AES-192-GCM', 'AES-256-GCM') AND {LENGTHS}"
ORIGINAL = f"encryption_algorithm = 'AES-256-GCM' AND {LENGTHS}"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "files", type_="check")
    op.create_check_constraint(CONSTRAINT, "files", WIDENED)

    # Raise the readiness marker last, so a failure part-way never advertises a schema the
    # database does not have. The release gate compares this against the running code.
    op.execute(
        sa.text(
            f"ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision SET DEFAULT '{revision}'"
        )
    )
    op.execute(sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{revision}' WHERE id = 1"))


def downgrade() -> None:
    remaining = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM files WHERE encryption_algorithm <> 'AES-256-GCM'"))
        .scalar_one()
    )
    if remaining:
        raise RuntimeError(
            f"{remaining} file(s) are encrypted under AES-128-GCM or AES-192-GCM. "
            "Downgrading would make the constraint reject rows that are already stored, "
            "and those files are still decryptable. Re-encrypt or delete them first."
        )
    op.execute(
        sa.text(
            "ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision "
            f"SET DEFAULT '{down_revision}'"
        )
    )
    op.execute(
        sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{down_revision}' WHERE id = 1")
    )
    op.drop_constraint(CONSTRAINT, "files", type_="check")
    op.create_check_constraint(CONSTRAINT, "files", ORIGINAL)
