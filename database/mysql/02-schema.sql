-- MySQL 8.4 empty-database schema installation.
--
-- Run this file exactly once as MySQL root/administrator, immediately after
-- 01-provision.sql. From the repository root on the database server:
--
--     sudo mysql < database/mysql/02-schema.sql
--     mysql --user=root --password < database/mysql/02-schema.sql
--
-- Never put the root password directly on the command line, never use an
-- interactive SOURCE command, and never use the mysql client's --force option.
-- For a remote application connection, use protected copies of all three SQL
-- files and replace every localhost account-host literal consistently in each
-- copy. Keep the environment-specific copies out of version control.
--
-- This script is deliberately non-idempotent and accepts only a completely
-- empty fyp_secure_file_platform schema. MySQL DDL is not fully transactional.
-- If any statement fails, do not rerun this file over the partial schema:
-- diagnose the failure, recreate the disposable empty database or restore the
-- verified pre-deployment backup, then restart from 01-provision.sql.
--
-- The DDL below is the flattened final state represented by revisions
-- 0001_initial through 0011_must_change_password. Production deployment does not
-- run Alembic. The alembic_version row is retained only as a compatibility
-- marker for development tooling and must be updated together with reviewed
-- future root-executed SQL release scripts.

USE `fyp_secure_file_platform`;
SET SESSION time_zone = '+00:00';

-- Fail closed before permanent DDL unless this is Oracle MySQL 8.4 in strict
-- mode, the database encoding is exact, and no persistent schema object exists.
CREATE TEMPORARY TABLE fyp_schema_install_guard (
    preflight_ok TINYINT NOT NULL,
    CONSTRAINT ck_fyp_schema_install_preflight CHECK (preflight_ok = 1)
) ENGINE=InnoDB;

INSERT INTO fyp_schema_install_guard (preflight_ok)
SELECT CASE
    WHEN SUBSTRING_INDEX(VERSION(), '.', 2) = '8.4'
     AND LOWER(CONCAT(VERSION(), ' ', @@version_comment)) NOT LIKE '%mariadb%'
     AND (
         FIND_IN_SET('STRICT_TRANS_TABLES', @@SESSION.sql_mode) > 0
         OR FIND_IN_SET('STRICT_ALL_TABLES', @@SESSION.sql_mode) > 0
     )
     AND (
         SELECT COUNT(*)
         FROM information_schema.SCHEMATA
         WHERE SCHEMA_NAME = DATABASE()
           AND DEFAULT_CHARACTER_SET_NAME = 'utf8mb4'
           AND DEFAULT_COLLATION_NAME = 'utf8mb4_unicode_ci'
     ) = 1
     AND (
         SELECT COUNT(*)
         FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
     ) = 0
     AND (
         SELECT COUNT(*)
         FROM information_schema.ROUTINES
         WHERE ROUTINE_SCHEMA = DATABASE()
     ) = 0
     AND (
         SELECT COUNT(*)
         FROM information_schema.TRIGGERS
         WHERE TRIGGER_SCHEMA = DATABASE()
     ) = 0
     AND (
         SELECT COUNT(*)
         FROM information_schema.EVENTS
         WHERE EVENT_SCHEMA = DATABASE()
     ) = 0
    THEN 1
    ELSE 0
END;

DROP TEMPORARY TABLE fyp_schema_install_guard;

CREATE TABLE auth_login_throttles (
    scope ENUM(
        'ACCOUNT',
        'IP',
        'REAUTH_ACCOUNT',
        'REAUTH_IP',
        'REGISTRATION_IP',
        'VERIFICATION_SEND_EMAIL',
        'VERIFICATION_SEND_IP',
        'VERIFICATION_CHECK_EMAIL',
        'VERIFICATION_CHECK_IP'
    ) NOT NULL,
    key_hash CHAR(64) NOT NULL,
    failed_count INTEGER UNSIGNED NOT NULL DEFAULT '0',
    window_started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    blocked_until DATETIME,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scope, key_hash)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_auth_login_throttles_blocked_until
    ON auth_login_throttles (blocked_until);
CREATE INDEX idx_auth_login_throttles_updated_at
    ON auth_login_throttles (updated_at);

CREATE TABLE recovery_keys (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    key_uuid CHAR(36) NOT NULL,
    public_key_pem TEXT NOT NULL,
    algorithm VARCHAR(50) NOT NULL DEFAULT 'RSA-OAEP-SHA256',
    key_size_bits SMALLINT UNSIGNED NOT NULL DEFAULT '3072',
    fingerprint CHAR(64) NOT NULL,
    status ENUM('ACTIVE', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT uq_recovery_keys_key_uuid UNIQUE (key_uuid),
    CONSTRAINT uq_recovery_keys_fingerprint UNIQUE (fingerprint),
    CONSTRAINT ck_recovery_keys_supported_size
        CHECK (key_size_bits IN (2048, 3072, 4096)),
    CONSTRAINT ck_recovery_keys_status_revoked_at CHECK (
        (status = 'ACTIVE' AND revoked_at IS NULL)
        OR (status = 'REVOKED' AND revoked_at IS NOT NULL)
    )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_recovery_keys_created_at ON recovery_keys (created_at);
CREATE INDEX idx_recovery_keys_status ON recovery_keys (status);

CREATE TABLE users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_uuid CHAR(36) NOT NULL,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    `role` ENUM('USER', 'ADMIN', 'RECOVERY_OFFICER') NOT NULL DEFAULT 'USER',
    status ENUM('ACTIVE', 'DISABLED', 'DELETED') NOT NULL DEFAULT 'ACTIVE',
    email_verified BOOL NOT NULL DEFAULT '0',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    password_changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME,
    avatar_object_key VARCHAR(500),
    avatar_content_type VARCHAR(64),
    avatar_sha256 CHAR(64),
    avatar_bytes INTEGER UNSIGNED,
    avatar_updated_at DATETIME,
    must_change_password BOOL NOT NULL DEFAULT '0',
    PRIMARY KEY (id),
    CONSTRAINT uq_users_user_uuid UNIQUE (user_uuid),
    CONSTRAINT uq_users_username UNIQUE (username),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_avatar_shape CHECK (
        (avatar_object_key IS NULL AND avatar_content_type IS NULL
         AND avatar_sha256 IS NULL AND avatar_bytes IS NULL AND avatar_updated_at IS NULL)
        OR (avatar_object_key IS NOT NULL AND avatar_content_type IN ('image/png', 'image/jpeg')
            AND avatar_sha256 REGEXP '^[0-9a-f]{64}$' AND avatar_bytes BETWEEN 1 AND 524288
            AND avatar_updated_at IS NOT NULL)
    )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_users_created_at ON users (created_at);
CREATE INDEX idx_users_role ON users (`role`);
CREATE INDEX idx_users_status ON users (status);

CREATE TABLE audit_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    actor_user_id BIGINT UNSIGNED,
    action VARCHAR(100) NOT NULL,
    resource_type ENUM(
        'AUTH',
        'USER',
        'FILE',
        'SHARE',
        'RECOVERY',
        'INTEGRITY',
        'SYSTEM'
    ) NOT NULL,
    resource_id VARCHAR(100),
    target_user_id BIGINT UNSIGNED,
    result ENUM('SUCCESS', 'FAIL') NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    description TEXT,
    metadata_json JSON NOT NULL,
    previous_hash CHAR(64),
    current_hash CHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_audit_logs_actor_user
        FOREIGN KEY (actor_user_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_audit_logs_target_user
        FOREIGN KEY (target_user_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_audit_logs_action ON audit_logs (action);
CREATE INDEX idx_audit_logs_actor_user_id ON audit_logs (actor_user_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX idx_audit_logs_created_id ON audit_logs (created_at, id);
CREATE INDEX idx_audit_logs_resource ON audit_logs (resource_type, resource_id);
CREATE INDEX idx_audit_logs_resource_created_id
    ON audit_logs (resource_type, resource_id, created_at, id);
CREATE INDEX idx_audit_logs_result ON audit_logs (result);
CREATE INDEX idx_audit_logs_target_user_id ON audit_logs (target_user_id);

CREATE TABLE file_folders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    folder_uuid CHAR(36) NOT NULL,
    owner_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(80) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_file_folders_folder_uuid UNIQUE (folder_uuid),
    CONSTRAINT uq_file_folders_owner_name UNIQUE (owner_id, name),
    CONSTRAINT fk_file_folders_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_file_folders_owner_name ON file_folders (owner_id, name);

CREATE TABLE files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    file_uuid CHAR(36) NOT NULL,
    owner_id BIGINT UNSIGNED NOT NULL,
    folder_id BIGINT UNSIGNED,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    storage_object_key VARCHAR(500) NOT NULL,
    mime_type VARCHAR(150),
    file_size_bytes BIGINT UNSIGNED NOT NULL,
    encrypted_size_bytes BIGINT UNSIGNED,
    envelope_version SMALLINT UNSIGNED NOT NULL DEFAULT '1',
    aad_version SMALLINT UNSIGNED NOT NULL DEFAULT '1',
    encryption_algorithm VARCHAR(50) NOT NULL DEFAULT 'AES-256-GCM',
    iv VARBINARY(32) NOT NULL,
    auth_tag VARBINARY(32) NOT NULL,
    encrypted_sha256 CHAR(64) NOT NULL,
    encrypted_manifest BLOB,
    status ENUM('ACTIVE', 'DELETED', 'CORRUPTED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME,
    revision INTEGER UNSIGNED NOT NULL DEFAULT '1',
    PRIMARY KEY (id),
    CONSTRAINT uq_files_file_uuid UNIQUE (file_uuid),
    CONSTRAINT uq_files_stored_filename UNIQUE (stored_filename),
    CONSTRAINT uq_files_storage_object_key UNIQUE (storage_object_key),
    CONSTRAINT ck_files_versions
        CHECK (envelope_version >= 1 AND aad_version >= 1 AND revision >= 1),
    CONSTRAINT ck_files_nonnegative_sizes CHECK (
        file_size_bytes >= 0
        AND (encrypted_size_bytes IS NULL OR encrypted_size_bytes >= 0)
    ),
    CONSTRAINT ck_files_encryption_envelope CHECK (
        (
            (encryption_algorithm COLLATE utf8mb4_bin
                IN ('AES-128-GCM', 'AES-192-GCM', 'AES-256-GCM', 'AES-256-GCM-SIV', 'ChaCha20-Poly1305')
             AND OCTET_LENGTH(iv) = 12)
            OR (encryption_algorithm COLLATE utf8mb4_bin = 'XChaCha20-Poly1305'
             AND OCTET_LENGTH(iv) = 24)
        )
        AND OCTET_LENGTH(auth_tag) = 16
    ),
    CONSTRAINT ck_files_encrypted_sha256
        CHECK (encrypted_sha256 REGEXP '^[0-9a-f]{64}$'),
    CONSTRAINT ck_files_encrypted_manifest_size
        CHECK (encrypted_manifest IS NULL OR OCTET_LENGTH(encrypted_manifest) <= 65535),
    CONSTRAINT ck_files_status_deleted_at CHECK (
        (status = 'DELETED' AND deleted_at IS NOT NULL)
        OR (status IN ('ACTIVE', 'CORRUPTED') AND deleted_at IS NULL)
    ),
    CONSTRAINT fk_files_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_files_folder
        FOREIGN KEY (folder_id) REFERENCES file_folders (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_files_created_at ON files (created_at);
CREATE INDEX idx_files_folder_id ON files (folder_id);
CREATE INDEX idx_files_owner_id ON files (owner_id);
CREATE INDEX idx_files_owner_status_created
    ON files (owner_id, status, created_at, id);
CREATE INDEX idx_files_status ON files (status);

CREATE TABLE user_keys (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    key_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    public_key_pem TEXT NOT NULL,
    algorithm VARCHAR(50) NOT NULL DEFAULT 'RSA-OAEP-SHA256',
    key_size_bits SMALLINT UNSIGNED NOT NULL DEFAULT '3072',
    fingerprint CHAR(64) NOT NULL,
    custody_mode ENUM('LEGACY_EXTERNAL', 'CLIENT_WRAPPED')
        NOT NULL DEFAULT 'LEGACY_EXTERNAL',
    status ENUM('ACTIVE', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT uq_user_keys_key_uuid UNIQUE (key_uuid),
    CONSTRAINT uq_user_keys_fingerprint UNIQUE (fingerprint),
    CONSTRAINT uq_user_keys_id_user_id UNIQUE (id, user_id),
    CONSTRAINT ck_user_keys_supported_size
        CHECK (key_size_bits IN (2048, 3072, 4096)),
    CONSTRAINT ck_user_keys_status_revoked_at CHECK (
        (status = 'ACTIVE' AND revoked_at IS NULL)
        OR (status = 'REVOKED' AND revoked_at IS NOT NULL)
    ),
    CONSTRAINT fk_user_keys_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_user_keys_created_at ON user_keys (created_at);
CREATE INDEX idx_user_keys_status ON user_keys (status);
CREATE INDEX idx_user_keys_user_id ON user_keys (user_id);
CREATE INDEX idx_user_keys_user_status ON user_keys (user_id, status);

CREATE TABLE user_key_protection_profiles (
    user_id BIGINT UNSIGNED NOT NULL,
    profile_uuid CHAR(36) NOT NULL,
    format_version SMALLINT UNSIGNED NOT NULL DEFAULT '1',
    kdf_algorithm VARCHAR(30) NOT NULL DEFAULT 'ARGON2ID',
    kdf_version SMALLINT UNSIGNED NOT NULL DEFAULT '19',
    kdf_salt VARBINARY(32) NOT NULL,
    kdf_memory_kib INTEGER UNSIGNED NOT NULL,
    kdf_iterations SMALLINT UNSIGNED NOT NULL,
    kdf_parallelism SMALLINT UNSIGNED NOT NULL,
    derived_key_length SMALLINT UNSIGNED NOT NULL DEFAULT '32',
    amk_wrapping_algorithm VARCHAR(50) NOT NULL DEFAULT 'AES-256-GCM',
    wrapped_amk VARBINARY(64) NOT NULL,
    amk_nonce VARBINARY(32) NOT NULL,
    amk_auth_tag VARBINARY(32) NOT NULL,
    aad_version SMALLINT UNSIGNED NOT NULL DEFAULT '1',
    revision INTEGER UNSIGNED NOT NULL DEFAULT '1',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (user_id),
    CONSTRAINT uq_user_key_protection_profiles_uuid UNIQUE (profile_uuid),
    CONSTRAINT ck_user_key_protection_profiles_versions
        CHECK (format_version >= 1 AND aad_version >= 1 AND revision >= 1),
    CONSTRAINT ck_user_key_protection_profiles_kdf_suite CHECK (
        kdf_algorithm = 'ARGON2ID'
        AND kdf_version = 19
        AND derived_key_length = 32
    ),
    CONSTRAINT ck_user_key_protection_profiles_kdf_bounds CHECK (
        kdf_memory_kib BETWEEN 65536 AND 1048576
        AND kdf_iterations BETWEEN 1 AND 20
        AND kdf_parallelism BETWEEN 1 AND 16
    ),
    CONSTRAINT ck_user_key_protection_profiles_salt_length
        CHECK (OCTET_LENGTH(kdf_salt) BETWEEN 16 AND 32),
    CONSTRAINT ck_user_key_protection_profiles_amk_envelope CHECK (
        amk_wrapping_algorithm = 'AES-256-GCM'
        AND OCTET_LENGTH(wrapped_amk) = 32
        AND OCTET_LENGTH(amk_nonce) = 12
        AND OCTET_LENGTH(amk_auth_tag) = 16
    ),
    CONSTRAINT fk_user_key_protection_profiles_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE encrypted_private_key_bundles (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    bundle_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    user_key_id BIGINT UNSIGNED NOT NULL,
    format_version SMALLINT UNSIGNED NOT NULL DEFAULT '1',
    private_key_format VARCHAR(30) NOT NULL DEFAULT 'PKCS8-DER',
    derivation_algorithm VARCHAR(30) NOT NULL DEFAULT 'HKDF-SHA256',
    derivation_salt VARBINARY(32) NOT NULL,
    encryption_algorithm VARCHAR(50) NOT NULL DEFAULT 'AES-256-GCM',
    encrypted_private_key BLOB NOT NULL,
    nonce VARBINARY(32) NOT NULL,
    auth_tag VARBINARY(32) NOT NULL,
    aad_version SMALLINT UNSIGNED NOT NULL DEFAULT '1',
    ciphertext_sha256 CHAR(64) NOT NULL,
    revision INTEGER UNSIGNED NOT NULL DEFAULT '1',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT uq_encrypted_private_key_bundles_uuid UNIQUE (bundle_uuid),
    CONSTRAINT uq_encrypted_private_key_bundles_user_key UNIQUE (user_key_id),
    CONSTRAINT ck_encrypted_private_key_bundles_versions
        CHECK (format_version >= 1 AND aad_version >= 1 AND revision >= 1),
    CONSTRAINT ck_encrypted_private_key_bundles_crypto_suite CHECK (
        private_key_format = 'PKCS8-DER'
        AND derivation_algorithm = 'HKDF-SHA256'
        AND encryption_algorithm = 'AES-256-GCM'
    ),
    CONSTRAINT ck_encrypted_private_key_bundles_envelope CHECK (
        OCTET_LENGTH(derivation_salt) BETWEEN 16 AND 32
        AND OCTET_LENGTH(nonce) = 12
        AND OCTET_LENGTH(auth_tag) = 16
        AND OCTET_LENGTH(encrypted_private_key) BETWEEN 1 AND 16384
    ),
    CONSTRAINT ck_encrypted_private_key_bundles_sha256
        CHECK (ciphertext_sha256 REGEXP '^[0-9a-f]{64}$'),
    CONSTRAINT fk_encrypted_private_key_bundles_profile
        FOREIGN KEY (user_id) REFERENCES user_key_protection_profiles (user_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_encrypted_private_key_bundles_user_key_owner
        FOREIGN KEY (user_key_id, user_id) REFERENCES user_keys (id, user_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_encrypted_private_key_bundles_user_id
    ON encrypted_private_key_bundles (user_id);
CREATE INDEX idx_encrypted_private_key_bundles_user_key_owner
    ON encrypted_private_key_bundles (user_key_id, user_id);

CREATE TABLE user_sessions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    session_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    access_token_hash CHAR(64) NOT NULL,
    status ENUM('ACTIVE', 'EXPIRED', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    access_expires_at DATETIME NOT NULL,
    absolute_expires_at DATETIME NOT NULL,
    revoked_at DATETIME,
    revoked_reason VARCHAR(100),
    PRIMARY KEY (id),
    CONSTRAINT uq_user_sessions_session_uuid UNIQUE (session_uuid),
    CONSTRAINT uq_user_sessions_access_token_hash UNIQUE (access_token_hash),
    CONSTRAINT ck_user_sessions_access_before_absolute
        CHECK (access_expires_at <= absolute_expires_at),
    CONSTRAINT fk_user_sessions_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_user_sessions_created_at ON user_sessions (created_at);
CREATE INDEX idx_user_sessions_status_access_expires
    ON user_sessions (status, access_expires_at);
CREATE INDEX idx_user_sessions_status_absolute_expires
    ON user_sessions (status, absolute_expires_at);
CREATE INDEX idx_user_sessions_user_status
    ON user_sessions (user_id, status);

CREATE TABLE audit_chain_heads (
    id TINYINT UNSIGNED NOT NULL,
    last_log_id BIGINT UNSIGNED,
    current_hash CHAR(64) NOT NULL,
    schema_revision VARCHAR(64) NOT NULL DEFAULT '0002_auth_identity_sessions',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT ck_audit_chain_heads_singleton CHECK (id = 1),
    CONSTRAINT fk_audit_chain_heads_last_log
        FOREIGN KEY (last_log_id) REFERENCES audit_logs (id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE file_access_grants (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    file_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    granted_by BIGINT UNSIGNED NOT NULL,
    can_download BOOL NOT NULL DEFAULT '1',
    can_share BOOL NOT NULL DEFAULT '0',
    can_revoke BOOL NOT NULL DEFAULT '0',
    can_manage BOOL NOT NULL DEFAULT '0',
    status ENUM('ACTIVE', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,
    revision INTEGER UNSIGNED NOT NULL DEFAULT '1',
    folder_id BIGINT UNSIGNED,
    PRIMARY KEY (id),
    CONSTRAINT uq_file_access_grants_file_user UNIQUE (file_id, user_id),
    CONSTRAINT ck_file_access_grants_status_revoked_at CHECK (
        (status = 'ACTIVE' AND revoked_at IS NULL)
        OR (status = 'REVOKED' AND revoked_at IS NOT NULL)
    ),
    CONSTRAINT ck_file_access_grants_revision CHECK (revision >= 1),
    CONSTRAINT fk_file_access_grants_file
        FOREIGN KEY (file_id) REFERENCES files (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_file_access_grants_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_file_access_grants_granted_by
        FOREIGN KEY (granted_by) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_file_access_grants_folder
        FOREIGN KEY (folder_id) REFERENCES file_folders (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_file_access_grants_created_at
    ON file_access_grants (created_at);
CREATE INDEX idx_file_access_grants_file_id
    ON file_access_grants (file_id);
CREATE INDEX idx_file_access_grants_folder_id
    ON file_access_grants (folder_id);
CREATE INDEX idx_file_access_grants_granted_by
    ON file_access_grants (granted_by);
CREATE INDEX idx_file_access_grants_status
    ON file_access_grants (status);
CREATE INDEX idx_file_access_grants_user_id
    ON file_access_grants (user_id);
CREATE INDEX idx_file_access_grants_user_status_file
    ON file_access_grants (user_id, status, file_id);

CREATE TABLE file_key_wrappings (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    file_id BIGINT UNSIGNED NOT NULL,
    recipient_type ENUM('USER', 'RECOVERY') NOT NULL,
    recipient_user_id BIGINT UNSIGNED,
    user_key_id BIGINT UNSIGNED,
    recovery_key_id BIGINT UNSIGNED,
    wrapped_file_key VARBINARY(1024) NOT NULL,
    wrapping_algorithm VARCHAR(50) NOT NULL DEFAULT 'RSA-OAEP-SHA256',
    status ENUM('ACTIVE', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,
    revision INTEGER UNSIGNED NOT NULL DEFAULT '1',
    PRIMARY KEY (id),
    CONSTRAINT uq_file_key_wrappings_file_user_key
        UNIQUE (file_id, recipient_user_id, user_key_id),
    CONSTRAINT uq_file_key_wrappings_file_recovery_key
        UNIQUE (file_id, recovery_key_id),
    CONSTRAINT ck_file_key_wrappings_recipient_shape CHECK (
        (
            recipient_type = 'USER'
            AND recipient_user_id IS NOT NULL
            AND user_key_id IS NOT NULL
            AND recovery_key_id IS NULL
        )
        OR (
            recipient_type = 'RECOVERY'
            AND recipient_user_id IS NULL
            AND user_key_id IS NULL
            AND recovery_key_id IS NOT NULL
        )
    ),
    CONSTRAINT ck_file_key_wrappings_envelope CHECK (
        wrapping_algorithm = 'RSA-OAEP-SHA256'
        AND OCTET_LENGTH(wrapped_file_key) BETWEEN 256 AND 512
    ),
    CONSTRAINT ck_file_key_wrappings_status_revoked_at CHECK (
        (status = 'ACTIVE' AND revoked_at IS NULL)
        OR (status = 'REVOKED' AND revoked_at IS NOT NULL)
    ),
    CONSTRAINT ck_file_key_wrappings_revision CHECK (revision >= 1),
    CONSTRAINT fk_file_key_wrappings_file
        FOREIGN KEY (file_id) REFERENCES files (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_file_key_wrappings_recipient_user
        FOREIGN KEY (recipient_user_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_file_key_wrappings_user_key_owner
        FOREIGN KEY (user_key_id, recipient_user_id)
        REFERENCES user_keys (id, user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_file_key_wrappings_recovery_key
        FOREIGN KEY (recovery_key_id) REFERENCES recovery_keys (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_file_key_wrappings_created_at
    ON file_key_wrappings (created_at);
CREATE INDEX idx_file_key_wrappings_file_id
    ON file_key_wrappings (file_id);
CREATE INDEX idx_file_key_wrappings_recipient_type
    ON file_key_wrappings (recipient_type);
CREATE INDEX idx_file_key_wrappings_recipient_user_id
    ON file_key_wrappings (recipient_user_id);
CREATE INDEX idx_file_key_wrappings_recipient_status_file_key
    ON file_key_wrappings (recipient_user_id, status, file_id, user_key_id);
CREATE INDEX idx_file_key_wrappings_recovery_key_id
    ON file_key_wrappings (recovery_key_id);
CREATE INDEX idx_file_key_wrappings_status
    ON file_key_wrappings (status);
CREATE INDEX idx_file_key_wrappings_user_key_id
    ON file_key_wrappings (user_key_id);
CREATE INDEX idx_file_key_wrappings_user_key_owner
    ON file_key_wrappings (user_key_id, recipient_user_id);

CREATE TABLE integrity_checks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    file_id BIGINT UNSIGNED NOT NULL,
    checked_by BIGINT UNSIGNED,
    expected_hash CHAR(64) NOT NULL,
    actual_hash CHAR(64),
    result ENUM('VALID', 'MODIFIED', 'MISSING', 'ERROR') NOT NULL,
    message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_integrity_checks_file
        FOREIGN KEY (file_id) REFERENCES files (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_integrity_checks_checked_by
        FOREIGN KEY (checked_by) REFERENCES users (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_integrity_checks_checked_by
    ON integrity_checks (checked_by);
CREATE INDEX idx_integrity_checks_created_at
    ON integrity_checks (created_at);
CREATE INDEX idx_integrity_checks_file_id
    ON integrity_checks (file_id);
CREATE INDEX idx_integrity_checks_result
    ON integrity_checks (result);

CREATE TABLE recovery_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_uuid CHAR(36) NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    requested_by BIGINT UNSIGNED NOT NULL,
    approved_by BIGINT UNSIGNED,
    executed_by BIGINT UNSIGNED,
    target_user_key_id BIGINT UNSIGNED,
    result_wrapping_id BIGINT UNSIGNED,
    reason TEXT NOT NULL,
    rejection_reason TEXT,
    status ENUM(
        'PENDING',
        'APPROVED',
        'REJECTED',
        'EXECUTED',
        'CANCELLED'
    ) NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    approved_at DATETIME,
    rejected_at DATETIME,
    executed_at DATETIME,
    cancelled_at DATETIME,
    revision INTEGER UNSIGNED NOT NULL DEFAULT '1',
    PRIMARY KEY (id),
    CONSTRAINT uq_recovery_requests_request_uuid UNIQUE (request_uuid),
    CONSTRAINT ck_recovery_requests_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT ck_recovery_requests_maker_checker
        CHECK (approved_by IS NULL OR approved_by <> requested_by),
    CONSTRAINT ck_recovery_requests_revision CHECK (revision >= 1),
    CONSTRAINT ck_recovery_requests_status_timestamps CHECK (
        (
            status = 'PENDING'
            AND approved_at IS NULL
            AND rejected_at IS NULL
            AND executed_at IS NULL
            AND cancelled_at IS NULL
        )
        OR (
            status = 'APPROVED'
            AND approved_at IS NOT NULL
            AND rejected_at IS NULL
            AND executed_at IS NULL
            AND cancelled_at IS NULL
        )
        OR (
            status = 'REJECTED'
            AND approved_at IS NULL
            AND rejected_at IS NOT NULL
            AND executed_at IS NULL
            AND cancelled_at IS NULL
        )
        OR (
            status = 'EXECUTED'
            AND approved_at IS NOT NULL
            AND rejected_at IS NULL
            AND executed_at IS NOT NULL
            AND cancelled_at IS NULL
        )
        OR (
            status = 'CANCELLED'
            AND approved_at IS NULL
            AND rejected_at IS NULL
            AND executed_at IS NULL
            AND cancelled_at IS NOT NULL
        )
    ),
    CONSTRAINT ck_recovery_requests_result_status
        CHECK (result_wrapping_id IS NULL OR status = 'EXECUTED'),
    CONSTRAINT fk_recovery_requests_file
        FOREIGN KEY (file_id) REFERENCES files (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_recovery_requests_requested_by
        FOREIGN KEY (requested_by) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_recovery_requests_approved_by
        FOREIGN KEY (approved_by) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_recovery_requests_executed_by
        FOREIGN KEY (executed_by) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_recovery_requests_target_key_owner
        FOREIGN KEY (target_user_key_id, requested_by)
        REFERENCES user_keys (id, user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_recovery_requests_result_wrapping
        FOREIGN KEY (result_wrapping_id) REFERENCES file_key_wrappings (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_recovery_requests_approved_by
    ON recovery_requests (approved_by);
CREATE INDEX idx_recovery_requests_created_at
    ON recovery_requests (created_at);
CREATE INDEX idx_recovery_requests_executed_by
    ON recovery_requests (executed_by);
CREATE INDEX idx_recovery_requests_file_id
    ON recovery_requests (file_id);
CREATE INDEX idx_recovery_requests_requested_by
    ON recovery_requests (requested_by);
CREATE INDEX idx_recovery_requests_result_wrapping_id
    ON recovery_requests (result_wrapping_id);
CREATE INDEX idx_recovery_requests_status
    ON recovery_requests (status);
CREATE INDEX idx_recovery_requests_status_created
    ON recovery_requests (status, created_at, id);
CREATE INDEX idx_recovery_requests_target_user_key_id
    ON recovery_requests (target_user_key_id);
CREATE INDEX idx_recovery_requests_target_key_owner
    ON recovery_requests (target_user_key_id, requested_by);

CREATE TABLE session_refresh_tokens (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    session_id BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL,
    generation INTEGER UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME,
    revoked_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT uq_session_refresh_tokens_token_hash UNIQUE (token_hash),
    CONSTRAINT uq_session_refresh_tokens_session_generation
        UNIQUE (session_id, generation),
    CONSTRAINT ck_session_refresh_tokens_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT fk_session_refresh_tokens_session
        FOREIGN KEY (session_id) REFERENCES user_sessions (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_session_refresh_tokens_expires_at
    ON session_refresh_tokens (expires_at);

-- Revision 0004. Stores only a keyed digest of each emailed challenge, never
-- the code itself, so a database reader cannot replay a pending challenge.
CREATE TABLE email_verification_codes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    code_uuid CHAR(36) NOT NULL,
    purpose ENUM('REGISTRATION', 'PASSWORD_RESET') NOT NULL,
    email VARCHAR(255) NOT NULL,
    user_id BIGINT UNSIGNED,
    code_hash CHAR(64) NOT NULL,
    status ENUM('PENDING', 'CONSUMED', 'INVALIDATED') NOT NULL DEFAULT 'PENDING',
    attempt_count INTEGER UNSIGNED NOT NULL DEFAULT '0',
    max_attempts INTEGER UNSIGNED NOT NULL DEFAULT '5',
    ip_address VARCHAR(45),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT uq_email_verification_codes_code_uuid UNIQUE (code_uuid),
    CONSTRAINT ck_email_verification_codes_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT ck_email_verification_codes_attempts
        CHECK (max_attempts >= 1 AND attempt_count <= max_attempts),
    CONSTRAINT ck_email_verification_codes_consumed_at
        CHECK (
            (status = 'CONSUMED' AND consumed_at IS NOT NULL)
            OR (status <> 'CONSUMED' AND consumed_at IS NULL)
        ),
    CONSTRAINT fk_email_verification_codes_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_email_verification_codes_lookup
    ON email_verification_codes (email, purpose, status, expires_at);
CREATE INDEX idx_email_verification_codes_user_id
    ON email_verification_codes (user_id);
CREATE INDEX idx_email_verification_codes_expires_at
    ON email_verification_codes (expires_at);
CREATE INDEX idx_email_verification_codes_created_at
    ON email_verification_codes (created_at);

-- Seed the only application bootstrap row with the last completed revision.
-- The final statement publishes 0004 only after every table, grant, and
-- compatibility marker below has succeeded.
INSERT INTO audit_chain_heads (
    id,
    last_log_id,
    current_hash,
    schema_revision
)
VALUES (
    1,
    NULL,
    '0000000000000000000000000000000000000000000000000000000000000000',
    '0002_auth_identity_sessions'
);

-- Grant the runtime identity CRUD only on ordinary application state. Audit
-- events remain append-only, the chain head can only be read/advanced, and the
-- runtime identity cannot change the schema compatibility marker.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`auth_login_throttles`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`encrypted_private_key_bundles`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`recovery_keys`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`users`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`files`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`file_folders`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`user_keys`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`user_key_protection_profiles`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`user_sessions`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`file_access_grants`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`file_key_wrappings`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`integrity_checks`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`recovery_requests`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`session_refresh_tokens`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON `fyp_secure_file_platform`.`email_verification_codes`
    TO 'fyp_user'@'localhost';
GRANT SELECT, INSERT
    ON `fyp_secure_file_platform`.`audit_logs`
    TO 'fyp_user'@'localhost';
GRANT SELECT, UPDATE (last_log_id, current_hash, updated_at)
    ON `fyp_secure_file_platform`.`audit_chain_heads`
    TO 'fyp_user'@'localhost';

-- Create the Alembic compatibility marker after every application object and
-- runtime grant. Readiness remains on the previous revision until the final
-- audit-chain marker update succeeds.
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

INSERT INTO alembic_version (version_num)
VALUES ('0011_must_change_password');

-- Restore final-schema default parity only after every prior install statement
-- has succeeded. The row still advertises 0002 until the final UPDATE below.
ALTER TABLE audit_chain_heads
ALTER COLUMN schema_revision SET DEFAULT '0011_must_change_password';

-- This must be the final statement: readiness reads this marker rather than
-- alembic_version because the runtime identity intentionally cannot read it.
UPDATE audit_chain_heads
SET schema_revision = '0011_must_change_password'
WHERE id = 1;
