"""Add client-wrapped account keys and harden file/recovery state.

Revision ID: 0003_client_key_custody
Revises: 0002_auth_identity_sessions
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003_client_key_custody"
down_revision: str | Sequence[str] | None = "0002_auth_identity_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def _guard_empty(result_sql: str, constraint_name: str) -> None:
    """Abort before permanent DDL when a legacy row cannot satisfy revision 0003."""
    table_name = f"guard_{constraint_name}"[:64]
    op.execute(sa.text(f"DROP TEMPORARY TABLE IF EXISTS {table_name}"))
    op.execute(
        sa.text(
            f"CREATE TEMPORARY TABLE {table_name} ("
            "preflight_ok TINYINT NOT NULL, "
            f"CONSTRAINT {constraint_name} CHECK (preflight_ok = 1)"
            ") ENGINE=InnoDB"
        )
    )
    op.execute(sa.text(f"INSERT INTO {table_name} (preflight_ok) {result_sql}"))
    op.execute(sa.text(f"DROP TEMPORARY TABLE {table_name}"))


def upgrade() -> None:
    # MySQL DDL implicitly commits between statements. Reject all known legacy
    # inconsistencies before the first permanent change instead of leaving a
    # partially upgraded schema.
    _guard_empty(
        "SELECT 0 FROM files GROUP BY storage_object_key HAVING COUNT(*) > 1 LIMIT 1",
        "ck_0003_unique_storage_keys",
    )
    _guard_empty(
        "SELECT 0 FROM user_keys WHERE "
        "(status = 'ACTIVE' AND revoked_at IS NOT NULL) OR "
        "(status = 'REVOKED' AND revoked_at IS NULL) LIMIT 1",
        "ck_0003_user_key_status",
    )
    _guard_empty(
        "SELECT 0 FROM recovery_keys WHERE "
        "(status = 'ACTIVE' AND revoked_at IS NOT NULL) OR "
        "(status = 'REVOKED' AND revoked_at IS NULL) LIMIT 1",
        "ck_0003_recovery_key_status",
    )
    _guard_empty(
        "SELECT 0 FROM file_access_grants WHERE "
        "(status = 'ACTIVE' AND revoked_at IS NOT NULL) OR "
        "(status = 'REVOKED' AND revoked_at IS NULL) LIMIT 1",
        "ck_0003_grant_status",
    )
    _guard_empty(
        "SELECT 0 FROM file_key_wrappings AS w LEFT JOIN user_keys AS k "
        "ON k.id = w.user_key_id WHERE "
        "NOT ((w.recipient_type = 'USER' AND w.recipient_user_id IS NOT NULL "
        "AND w.user_key_id IS NOT NULL AND w.recovery_key_id IS NULL "
        "AND k.user_id = w.recipient_user_id) OR "
        "(w.recipient_type = 'RECOVERY' AND w.recipient_user_id IS NULL "
        "AND w.user_key_id IS NULL AND w.recovery_key_id IS NOT NULL)) "
        "OR (w.status = 'ACTIVE' AND w.revoked_at IS NOT NULL) "
        "OR (w.status = 'REVOKED' AND w.revoked_at IS NULL) LIMIT 1",
        "ck_0003_wrapping_shape",
    )
    _guard_empty(
        "SELECT 0 FROM file_key_wrappings WHERE recipient_type = 'USER' "
        "GROUP BY file_id, recipient_user_id, user_key_id HAVING COUNT(*) > 1 LIMIT 1",
        "ck_0003_unique_user_wrap",
    )
    _guard_empty(
        "SELECT 0 FROM file_key_wrappings WHERE recipient_type = 'RECOVERY' "
        "GROUP BY file_id, recovery_key_id HAVING COUNT(*) > 1 LIMIT 1",
        "ck_0003_unique_recovery_wrap",
    )

    op.execute(
        sa.text(
            "ALTER TABLE audit_chain_heads ADD COLUMN "
            "schema_revision VARCHAR(64) NOT NULL "
            "DEFAULT '0002_auth_identity_sessions' AFTER current_hash"
        )
    )

    op.execute(sa.text("ALTER TABLE user_keys ADD COLUMN key_uuid CHAR(36) NULL AFTER id"))
    op.execute(
        sa.text(
            "ALTER TABLE user_keys ADD COLUMN key_size_bits "
            "SMALLINT UNSIGNED NOT NULL DEFAULT '3072' AFTER algorithm"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE user_keys ADD COLUMN custody_mode "
            "ENUM('LEGACY_EXTERNAL','CLIENT_WRAPPED') NOT NULL "
            "DEFAULT 'LEGACY_EXTERNAL' AFTER fingerprint"
        )
    )
    op.execute(sa.text("UPDATE user_keys SET key_uuid = UUID() WHERE key_uuid IS NULL"))
    op.alter_column("user_keys", "key_uuid", existing_type=sa.CHAR(length=36), nullable=False)
    op.create_unique_constraint("uq_user_keys_key_uuid", "user_keys", ["key_uuid"])
    op.create_unique_constraint("uq_user_keys_id_user_id", "user_keys", ["id", "user_id"])
    op.create_check_constraint(
        "ck_user_keys_supported_size", "user_keys", "key_size_bits IN (2048, 3072, 4096)"
    )
    op.create_check_constraint(
        "ck_user_keys_status_revoked_at",
        "user_keys",
        "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
        "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
    )
    op.create_index("idx_user_keys_user_status", "user_keys", ["user_id", "status"])

    op.execute(sa.text("ALTER TABLE recovery_keys ADD COLUMN key_uuid CHAR(36) NULL AFTER id"))
    op.execute(
        sa.text(
            "ALTER TABLE recovery_keys ADD COLUMN key_size_bits "
            "SMALLINT UNSIGNED NOT NULL DEFAULT '3072' AFTER algorithm"
        )
    )
    op.execute(sa.text("UPDATE recovery_keys SET key_uuid = UUID() WHERE key_uuid IS NULL"))
    op.alter_column("recovery_keys", "key_uuid", existing_type=sa.CHAR(length=36), nullable=False)
    op.create_unique_constraint("uq_recovery_keys_key_uuid", "recovery_keys", ["key_uuid"])
    op.create_check_constraint(
        "ck_recovery_keys_supported_size",
        "recovery_keys",
        "key_size_bits IN (2048, 3072, 4096)",
    )
    op.create_check_constraint(
        "ck_recovery_keys_status_revoked_at",
        "recovery_keys",
        "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
        "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
    )

    op.create_table(
        "user_key_protection_profiles",
        sa.Column("user_id", mysql.BIGINT(unsigned=True), autoincrement=False, nullable=False),
        sa.Column("profile_uuid", sa.CHAR(length=36), nullable=False),
        sa.Column(
            "format_version", mysql.SMALLINT(unsigned=True), server_default="1", nullable=False
        ),
        sa.Column("kdf_algorithm", sa.String(length=30), server_default="ARGON2ID", nullable=False),
        sa.Column(
            "kdf_version", mysql.SMALLINT(unsigned=True), server_default="19", nullable=False
        ),
        sa.Column("kdf_salt", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("kdf_memory_kib", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("kdf_iterations", mysql.SMALLINT(unsigned=True), nullable=False),
        sa.Column("kdf_parallelism", mysql.SMALLINT(unsigned=True), nullable=False),
        sa.Column(
            "derived_key_length", mysql.SMALLINT(unsigned=True), server_default="32", nullable=False
        ),
        sa.Column(
            "amk_wrapping_algorithm",
            sa.String(length=50),
            server_default="AES-256-GCM",
            nullable=False,
        ),
        sa.Column("wrapped_amk", mysql.VARBINARY(length=64), nullable=False),
        sa.Column("amk_nonce", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("amk_auth_tag", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("aad_version", mysql.SMALLINT(unsigned=True), server_default="1", nullable=False),
        sa.Column("revision", mysql.INTEGER(unsigned=True), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "format_version >= 1 AND aad_version >= 1 AND revision >= 1",
            name="ck_user_key_protection_profiles_versions",
        ),
        sa.CheckConstraint(
            "kdf_algorithm = 'ARGON2ID' AND kdf_version = 19 AND derived_key_length = 32",
            name="ck_user_key_protection_profiles_kdf_suite",
        ),
        sa.CheckConstraint(
            "kdf_memory_kib BETWEEN 65536 AND 1048576 AND kdf_iterations BETWEEN 1 AND 20 AND kdf_parallelism BETWEEN 1 AND 16",
            name="ck_user_key_protection_profiles_kdf_bounds",
        ),
        sa.CheckConstraint(
            "OCTET_LENGTH(kdf_salt) BETWEEN 16 AND 32",
            name="ck_user_key_protection_profiles_salt_length",
        ),
        sa.CheckConstraint(
            "amk_wrapping_algorithm = 'AES-256-GCM' AND OCTET_LENGTH(wrapped_amk) = 32 AND OCTET_LENGTH(amk_nonce) = 12 AND OCTET_LENGTH(amk_auth_tag) = 16",
            name="ck_user_key_protection_profiles_amk_envelope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_key_protection_profiles_user",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("profile_uuid", name="uq_user_key_protection_profiles_uuid"),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "encrypted_private_key_bundles",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("bundle_uuid", sa.CHAR(length=36), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_key_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "format_version", mysql.SMALLINT(unsigned=True), server_default="1", nullable=False
        ),
        sa.Column(
            "private_key_format", sa.String(length=30), server_default="PKCS8-DER", nullable=False
        ),
        sa.Column(
            "derivation_algorithm",
            sa.String(length=30),
            server_default="HKDF-SHA256",
            nullable=False,
        ),
        sa.Column("derivation_salt", mysql.VARBINARY(length=32), nullable=False),
        sa.Column(
            "encryption_algorithm",
            sa.String(length=50),
            server_default="AES-256-GCM",
            nullable=False,
        ),
        sa.Column("encrypted_private_key", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("auth_tag", mysql.VARBINARY(length=32), nullable=False),
        sa.Column("aad_version", mysql.SMALLINT(unsigned=True), server_default="1", nullable=False),
        sa.Column("ciphertext_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("revision", mysql.INTEGER(unsigned=True), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "format_version >= 1 AND aad_version >= 1 AND revision >= 1",
            name="ck_encrypted_private_key_bundles_versions",
        ),
        sa.CheckConstraint(
            "private_key_format = 'PKCS8-DER' AND derivation_algorithm = 'HKDF-SHA256' AND encryption_algorithm = 'AES-256-GCM'",
            name="ck_encrypted_private_key_bundles_crypto_suite",
        ),
        sa.CheckConstraint(
            "OCTET_LENGTH(derivation_salt) BETWEEN 16 AND 32 AND OCTET_LENGTH(nonce) = 12 AND OCTET_LENGTH(auth_tag) = 16 AND OCTET_LENGTH(encrypted_private_key) BETWEEN 1 AND 16384",
            name="ck_encrypted_private_key_bundles_envelope",
        ),
        sa.CheckConstraint(
            "ciphertext_sha256 REGEXP '^[0-9a-f]{64}$'",
            name="ck_encrypted_private_key_bundles_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_key_protection_profiles.user_id"],
            name="fk_encrypted_private_key_bundles_profile",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_key_id", "user_id"],
            ["user_keys.id", "user_keys.user_id"],
            name="fk_encrypted_private_key_bundles_user_key_owner",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_uuid", name="uq_encrypted_private_key_bundles_uuid"),
        sa.UniqueConstraint("user_key_id", name="uq_encrypted_private_key_bundles_user_key"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "idx_encrypted_private_key_bundles_user_id",
        "encrypted_private_key_bundles",
        ["user_id"],
    )
    op.create_index(
        "idx_encrypted_private_key_bundles_user_key_owner",
        "encrypted_private_key_bundles",
        ["user_key_id", "user_id"],
    )

    op.execute(
        sa.text(
            "ALTER TABLE files ADD COLUMN envelope_version "
            "SMALLINT UNSIGNED NOT NULL DEFAULT '1' AFTER encrypted_size_bytes"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE files ADD COLUMN aad_version "
            "SMALLINT UNSIGNED NOT NULL DEFAULT '1' AFTER envelope_version"
        )
    )
    op.execute(
        sa.text("ALTER TABLE files ADD COLUMN encrypted_manifest BLOB NULL AFTER encrypted_sha256")
    )
    op.execute(
        sa.text(
            "ALTER TABLE files ADD COLUMN revision "
            "INTEGER UNSIGNED NOT NULL DEFAULT '1' AFTER deleted_at"
        )
    )
    op.create_unique_constraint("uq_files_storage_object_key", "files", ["storage_object_key"])
    op.create_check_constraint(
        "ck_files_versions", "files", "envelope_version >= 1 AND aad_version >= 1 AND revision >= 1"
    )
    op.create_check_constraint(
        "ck_files_nonnegative_sizes",
        "files",
        "file_size_bytes >= 0 AND (encrypted_size_bytes IS NULL OR encrypted_size_bytes >= 0)",
    )
    op.create_check_constraint(
        "ck_files_encryption_envelope",
        "files",
        "encryption_algorithm = 'AES-256-GCM' AND OCTET_LENGTH(iv) = 12 AND OCTET_LENGTH(auth_tag) = 16",
    )
    op.create_check_constraint(
        "ck_files_encrypted_sha256", "files", "encrypted_sha256 REGEXP '^[0-9a-f]{64}$'"
    )
    op.create_check_constraint(
        "ck_files_encrypted_manifest_size",
        "files",
        "encrypted_manifest IS NULL OR OCTET_LENGTH(encrypted_manifest) <= 65535",
    )
    op.create_check_constraint(
        "ck_files_status_deleted_at",
        "files",
        "(status = 'DELETED' AND deleted_at IS NOT NULL) OR (status IN ('ACTIVE', 'CORRUPTED') AND deleted_at IS NULL)",
    )
    op.create_index(
        "idx_files_owner_status_created", "files", ["owner_id", "status", "created_at", "id"]
    )

    op.execute(
        sa.text(
            "ALTER TABLE file_access_grants ADD COLUMN updated_at "
            "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER created_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE file_access_grants ADD COLUMN revision "
            "INTEGER UNSIGNED NOT NULL DEFAULT '1' AFTER revoked_at"
        )
    )
    op.create_check_constraint(
        "ck_file_access_grants_status_revoked_at",
        "file_access_grants",
        "(status = 'ACTIVE' AND revoked_at IS NULL) OR (status = 'REVOKED' AND revoked_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_file_access_grants_revision", "file_access_grants", "revision >= 1"
    )
    op.create_index(
        "idx_file_access_grants_user_status_file",
        "file_access_grants",
        ["user_id", "status", "file_id"],
    )

    op.drop_constraint("fk_file_key_wrappings_user_key", "file_key_wrappings", type_="foreignkey")
    op.drop_constraint(
        "fk_file_key_wrappings_recipient_user", "file_key_wrappings", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_file_key_wrappings_recovery_key", "file_key_wrappings", type_="foreignkey"
    )
    op.execute(
        sa.text(
            "ALTER TABLE file_key_wrappings ADD COLUMN updated_at "
            "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER created_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE file_key_wrappings ADD COLUMN revision "
            "INTEGER UNSIGNED NOT NULL DEFAULT '1' AFTER revoked_at"
        )
    )
    op.create_unique_constraint(
        "uq_file_key_wrappings_file_user_key",
        "file_key_wrappings",
        ["file_id", "recipient_user_id", "user_key_id"],
    )
    op.create_unique_constraint(
        "uq_file_key_wrappings_file_recovery_key",
        "file_key_wrappings",
        ["file_id", "recovery_key_id"],
    )
    op.create_foreign_key(
        "fk_file_key_wrappings_recipient_user",
        "file_key_wrappings",
        "users",
        ["recipient_user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_file_key_wrappings_user_key_owner",
        "file_key_wrappings",
        "user_keys",
        ["user_key_id", "recipient_user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_file_key_wrappings_recovery_key",
        "file_key_wrappings",
        "recovery_keys",
        ["recovery_key_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_file_key_wrappings_recipient_shape",
        "file_key_wrappings",
        "(recipient_type = 'USER' AND recipient_user_id IS NOT NULL AND user_key_id IS NOT NULL AND recovery_key_id IS NULL) OR (recipient_type = 'RECOVERY' AND recipient_user_id IS NULL AND user_key_id IS NULL AND recovery_key_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_file_key_wrappings_envelope",
        "file_key_wrappings",
        "wrapping_algorithm = 'RSA-OAEP-SHA256' AND OCTET_LENGTH(wrapped_file_key) BETWEEN 256 AND 512",
    )
    op.create_check_constraint(
        "ck_file_key_wrappings_status_revoked_at",
        "file_key_wrappings",
        "(status = 'ACTIVE' AND revoked_at IS NULL) OR (status = 'REVOKED' AND revoked_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_file_key_wrappings_revision", "file_key_wrappings", "revision >= 1"
    )
    op.create_index(
        "idx_file_key_wrappings_recipient_status_file_key",
        "file_key_wrappings",
        ["recipient_user_id", "status", "file_id", "user_key_id"],
    )
    op.create_index(
        "idx_file_key_wrappings_user_key_owner",
        "file_key_wrappings",
        ["user_key_id", "recipient_user_id"],
    )

    op.drop_constraint("fk_integrity_checks_file", "integrity_checks", type_="foreignkey")
    op.create_foreign_key(
        "fk_integrity_checks_file",
        "integrity_checks",
        "files",
        ["file_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.drop_constraint("fk_recovery_requests_requested_by", "recovery_requests", type_="foreignkey")
    op.drop_constraint("fk_recovery_requests_approved_by", "recovery_requests", type_="foreignkey")
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN executed_by "
            "BIGINT UNSIGNED NULL AFTER approved_by"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN target_user_key_id "
            "BIGINT UNSIGNED NULL AFTER executed_by"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN result_wrapping_id "
            "BIGINT UNSIGNED NULL AFTER target_user_key_id"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN updated_at "
            "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER created_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN expires_at DATETIME NULL AFTER updated_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN cancelled_at DATETIME NULL AFTER executed_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE recovery_requests ADD COLUMN revision "
            "INTEGER UNSIGNED NOT NULL DEFAULT '1' AFTER cancelled_at"
        )
    )
    op.execute(
        sa.text(
            "UPDATE recovery_requests SET expires_at = DATE_ADD(created_at, INTERVAL 24 HOUR) WHERE expires_at IS NULL"
        )
    )
    op.alter_column("recovery_requests", "expires_at", existing_type=sa.DateTime(), nullable=False)
    op.create_foreign_key(
        "fk_recovery_requests_requested_by",
        "recovery_requests",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_recovery_requests_approved_by",
        "recovery_requests",
        "users",
        ["approved_by"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_recovery_requests_executed_by",
        "recovery_requests",
        "users",
        ["executed_by"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_recovery_requests_target_key_owner",
        "recovery_requests",
        "user_keys",
        ["target_user_key_id", "requested_by"],
        ["id", "user_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_recovery_requests_result_wrapping",
        "recovery_requests",
        "file_key_wrappings",
        ["result_wrapping_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_recovery_requests_expiry_after_creation", "recovery_requests", "expires_at > created_at"
    )
    op.create_check_constraint(
        "ck_recovery_requests_maker_checker",
        "recovery_requests",
        "approved_by IS NULL OR approved_by <> requested_by",
    )
    op.create_check_constraint(
        "ck_recovery_requests_revision", "recovery_requests", "revision >= 1"
    )
    op.create_check_constraint(
        "ck_recovery_requests_status_timestamps",
        "recovery_requests",
        "(status = 'PENDING' AND approved_at IS NULL AND rejected_at IS NULL AND executed_at IS NULL AND cancelled_at IS NULL) OR (status = 'APPROVED' AND approved_at IS NOT NULL AND rejected_at IS NULL AND executed_at IS NULL AND cancelled_at IS NULL) OR (status = 'REJECTED' AND approved_at IS NULL AND rejected_at IS NOT NULL AND executed_at IS NULL AND cancelled_at IS NULL) OR (status = 'EXECUTED' AND approved_at IS NOT NULL AND rejected_at IS NULL AND executed_at IS NOT NULL AND cancelled_at IS NULL) OR (status = 'CANCELLED' AND approved_at IS NULL AND rejected_at IS NULL AND executed_at IS NULL AND cancelled_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_recovery_requests_result_status",
        "recovery_requests",
        "result_wrapping_id IS NULL OR status = 'EXECUTED'",
    )
    op.create_index("idx_recovery_requests_executed_by", "recovery_requests", ["executed_by"])
    op.create_index(
        "idx_recovery_requests_target_user_key_id", "recovery_requests", ["target_user_key_id"]
    )
    op.create_index(
        "idx_recovery_requests_target_key_owner",
        "recovery_requests",
        ["target_user_key_id", "requested_by"],
    )
    op.create_index(
        "idx_recovery_requests_result_wrapping_id", "recovery_requests", ["result_wrapping_id"]
    )
    op.create_index(
        "idx_recovery_requests_status_created", "recovery_requests", ["status", "created_at", "id"]
    )

    op.create_index(
        "idx_audit_logs_resource_created_id",
        "audit_logs",
        ["resource_type", "resource_id", "created_at", "id"],
    )
    op.create_index("idx_audit_logs_created_id", "audit_logs", ["created_at", "id"])

    # Restore final-schema default parity immediately before publishing
    # readiness. The row marker update itself remains the final migration-body
    # statement after every required 0003 structure change succeeds.
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


def downgrade() -> None:
    op.execute(
        sa.text(
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
            "'0003_client_key_custody is irreversible; restore a backup or rebuild'"
        )
    )
