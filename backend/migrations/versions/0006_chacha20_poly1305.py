"""Allow ChaCha20-Poly1305 alongside the AES-GCM suites for file content.

Revision ID: 0006_chacha20_poly1305
Revises: 0005_selectable_aes_key_length
Create Date: 2026-09-02

A second AEAD construction rather than a fourth key length: a stream cipher authenticated by
Poly1305 (RFC 8439), where AES-GCM is a block cipher authenticated by GHASH. WebCrypto does
not provide it, so the browser gets it from @noble/ciphers.

Only the algorithm name widens. RFC 8439 specifies a 12-byte nonce and a 16-byte tag, which
are the lengths this constraint already requires, so the length half is untouched and the
stored columns keep their shapes. Existing rows all hold an AES name, which remains legal.

This revision also makes the name comparison case-sensitive. The column collates as
utf8mb4_unicode_ci, so the previous `IN (...)` matched case-insensitively and a row could hold
'aes-256-gcm'. That was never reachable through the API -- the Pydantic Literal is exact -- but
it made the constraint weaker than it reads, and a row that did slip through would be refused
by the browser at download time, because the client's name check *is* exact. Comparing under
utf8mb4_bin closes the gap. The flaw predates ChaCha20-Poly1305 and is fixed here because this
revision rewrites the same constraint.

Downgrading is only possible while no ChaCha20-Poly1305 file exists. Rather than delete rows
that are intact and decryptable, the downgrade refuses and says what to do about it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_chacha20_poly1305"
down_revision: str | Sequence[str] | None = "0005_selectable_aes_key_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_files_encryption_envelope"
LENGTHS = "OCTET_LENGTH(iv) = 12 AND OCTET_LENGTH(auth_tag) = 16"
AES_ONLY = "('AES-128-GCM', 'AES-192-GCM', 'AES-256-GCM')"
WITH_CHACHA = "('AES-128-GCM', 'AES-192-GCM', 'AES-256-GCM', 'ChaCha20-Poly1305')"

# COLLATE utf8mb4_bin makes the comparison exact; without it the column's _ci collation
# accepts any casing of these names.
WIDENED = f"encryption_algorithm COLLATE utf8mb4_bin IN {WITH_CHACHA} AND {LENGTHS}"
ORIGINAL = f"encryption_algorithm IN {AES_ONLY} AND {LENGTHS}"


def _count(sql: str) -> int:
    """Run a guard query, or return 0 when generating SQL offline with no connection."""
    if op.get_context().as_sql:
        return 0
    return op.get_bind().execute(sa.text(sql)).scalar_one()


def upgrade() -> None:
    # Tightening to an exact comparison would reject any row that had slipped in under a
    # different casing, so fail with a message naming them rather than with error 3819.
    # Offline SQL generation has no database to ask, so the check is skipped there and the
    # rendered script relies on the constraint itself to refuse a bad row.
    miscased = _count(
        "SELECT COUNT(*) FROM files WHERE encryption_algorithm COLLATE utf8mb4_bin "
        f"NOT IN {WITH_CHACHA}"
    )
    if miscased:
        raise RuntimeError(
            f"{miscased} file(s) hold an encryption_algorithm that is not exactly one of "
            f"{WITH_CHACHA}. The old constraint compared case-insensitively and let them "
            "through. Correct the casing before upgrading; the ciphertext is unaffected."
        )

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
        .execute(
            sa.text("SELECT COUNT(*) FROM files WHERE encryption_algorithm = 'ChaCha20-Poly1305'")
        )
        .scalar_one()
    )
    if remaining:
        raise RuntimeError(
            f"{remaining} file(s) are encrypted under ChaCha20-Poly1305. Downgrading would "
            "make the constraint reject rows that are already stored, and those files are "
            "still decryptable. Re-encrypt or delete them first."
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
