"""Allow AES-256-GCM-SIV and XChaCha20-Poly1305 for file content.

Revision ID: 0009_more_aead_suites
Revises: 0008_avatars
Create Date: 2026-10-02

Two more AEAD suites, both from @noble/ciphers in the browser (WebCrypto offers neither):

* AES-256-GCM-SIV (RFC 8452): AES with a synthetic IV, so a nonce that repeats by accident
  reveals only that the same file was encrypted twice and leaks no key material. 12-byte nonce,
  16-byte tag -- the shapes the constraint already allows.
* XChaCha20-Poly1305: ChaCha20-Poly1305 with a 24-byte nonce, large enough that a random nonce
  never realistically repeats. Its nonce is the one new shape, so the length half of the
  constraint becomes per-suite: 12 bytes for every other name, 24 for this one. `files.iv` is
  VARBINARY(32) already, so no column changes.

Existing rows all hold a name and a 12-byte nonce that remain legal. The comparison stays
exact (utf8mb4_bin), as 0006 made it.

Downgrading is only possible while no file uses either new suite; rather than delete intact,
decryptable files, the downgrade refuses and says what to do about them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_more_aead_suites"
down_revision: str | Sequence[str] | None = "0008_avatars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_files_encryption_envelope"
TWELVE_BYTE = (
    "('AES-128-GCM', 'AES-192-GCM', 'AES-256-GCM', 'AES-256-GCM-SIV', 'ChaCha20-Poly1305')"
)
WIDENED = (
    f"((encryption_algorithm COLLATE utf8mb4_bin IN {TWELVE_BYTE} AND OCTET_LENGTH(iv) = 12) "
    "OR (encryption_algorithm COLLATE utf8mb4_bin = 'XChaCha20-Poly1305' AND OCTET_LENGTH(iv) = 24)) "
    "AND OCTET_LENGTH(auth_tag) = 16"
)
PREVIOUS = (
    "encryption_algorithm COLLATE utf8mb4_bin IN "
    "('AES-128-GCM', 'AES-192-GCM', 'AES-256-GCM', 'ChaCha20-Poly1305') "
    "AND OCTET_LENGTH(iv) = 12 AND OCTET_LENGTH(auth_tag) = 16"
)


def _count(sql: str) -> int:
    """Run a guard query, or return 0 when generating SQL offline with no connection."""
    if op.get_context().as_sql:
        return 0
    return op.get_bind().execute(sa.text(sql)).scalar_one()


def _set_marker(value: str) -> None:
    op.execute(
        sa.text(f"ALTER TABLE audit_chain_heads ALTER COLUMN schema_revision SET DEFAULT '{value}'")
    )
    op.execute(sa.text(f"UPDATE audit_chain_heads SET schema_revision = '{value}' WHERE id = 1"))


def upgrade() -> None:
    # MySQL DDL cannot be rolled back: if the drop succeeded and the add failed, the table
    # would be left with no constraint. Refuse first if any row would fail the new one.
    failing = _count(f"SELECT COUNT(*) FROM files WHERE NOT ({WIDENED})")
    if failing:
        raise RuntimeError(
            f"{failing} file row(s) would fail the widened {CONSTRAINT}. Inspect them before "
            "upgrading; nothing was changed."
        )
    op.drop_constraint(CONSTRAINT, "files", type_="check")
    op.create_check_constraint(CONSTRAINT, "files", WIDENED)
    # The readiness marker goes last, so a failure part-way never advertises a schema the
    # database does not have.
    _set_marker(revision)


def downgrade() -> None:
    remaining = _count(
        "SELECT COUNT(*) FROM files WHERE encryption_algorithm COLLATE utf8mb4_bin "
        "IN ('AES-256-GCM-SIV', 'XChaCha20-Poly1305')"
    )
    if remaining:
        raise RuntimeError(
            f"{remaining} file(s) are encrypted under AES-256-GCM-SIV or XChaCha20-Poly1305. "
            "Downgrading would make the constraint reject rows that are already stored, and "
            "those files are still decryptable. Re-encrypt or delete them first."
        )
    _set_marker(str(down_revision))
    op.drop_constraint(CONSTRAINT, "files", type_="check")
    op.create_check_constraint(CONSTRAINT, "files", PREVIOUS)
