-- Read-only post-deployment verification for MySQL 8.4.
--
-- Run as MySQL root/administrator after 02-schema.sql. From the repository
-- root on the database server, execute it directly:
--
--     sudo mysql < database/mysql/03-verify.sql
--     mysql --user=root --password < database/mysql/03-verify.sql
--
-- Never put the root password directly on the command line, never use an
-- interactive SOURCE command, and never use the mysql client's --force option.
--
-- The exact account and schema-grant checks below expect localhost because
-- that is the tracked provisioning default. For a remote deployment, copy
-- all three SQL files outside the repository and replace every localhost
-- account-host literal consistently in all three protected copies before
-- running them. Keep the edited copies out of version control.
--
-- The administrator must be able to read the mysql grant tables and the
-- information_schema privilege views. Every query in this file is a SELECT.
-- Expected-empty result sets are called out below; any returned row requires
-- review before the application starts.

-- Expected: MySQL 8.4 (not MariaDB), strict SQL mode, and the deployment's
-- intended session time zone.
SELECT
    VERSION() AS mysql_version,
    @@version_comment AS version_comment,
    @@SESSION.sql_mode AS session_sql_mode,
    @@SESSION.time_zone AS session_time_zone,
    CASE
        WHEN SUBSTRING_INDEX(VERSION(), '.', 2) = '8.4'
         AND LOWER(CONCAT(VERSION(), ' ', @@version_comment)) NOT LIKE '%mariadb%'
        THEN 'OK'
        ELSE 'REVIEW'
    END AS mysql_84_status,
    CASE
        WHEN FIND_IN_SET('STRICT_TRANS_TABLES', @@SESSION.sql_mode) > 0
          OR FIND_IN_SET('STRICT_ALL_TABLES', @@SESSION.sql_mode) > 0
        THEN 'OK'
        ELSE 'REVIEW'
    END AS strict_mode_status;

-- Expected: one utf8mb4 / utf8mb4_unicode_ci database row.
SELECT
    COUNT(*) AS database_rows,
    MAX(DEFAULT_CHARACTER_SET_NAME) AS character_set,
    MAX(DEFAULT_COLLATION_NAME) AS collation,
    CASE
        WHEN COUNT(*) = 1
         AND MAX(DEFAULT_CHARACTER_SET_NAME) = 'utf8mb4'
         AND MAX(DEFAULT_COLLATION_NAME) = 'utf8mb4_unicode_ci'
        THEN 'OK'
        ELSE 'REVIEW'
    END AS database_status
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME = 'fyp_secure_file_platform';

-- Expected: exactly fyp_user@localhost, unlocked, unexpired, and with a
-- nonempty ssl_type. ANY represents REQUIRE SSL; X509 or SPECIFIED is stricter
-- and is also acceptable. The detail result also exposes any same-name account
-- at an unintended host.
SELECT
    User AS account_name,
    Host AS source_host,
    plugin AS authentication_plugin,
    ssl_type,
    account_locked,
    password_expired,
    CASE
        WHEN User = 'fyp_user'
         AND Host = 'localhost'
         AND plugin = 'caching_sha2_password'
         AND authentication_string <> ''
         AND ssl_type <> ''
         AND account_locked = 'N'
         AND password_expired = 'N'
        THEN 'EXPECTED'
        ELSE 'UNEXPECTED'
    END AS account_status
FROM mysql.user
WHERE User IN ('fyp_user', 'fyp_migrator')
ORDER BY User, Host;

SELECT
    COUNT(*) AS named_account_rows,
    COALESCE(SUM(
        User = 'fyp_user'
        AND Host = 'localhost'
        AND plugin = 'caching_sha2_password'
        AND authentication_string <> ''
        AND ssl_type <> ''
        AND account_locked = 'N'
        AND password_expired = 'N'
    ), 0) AS expected_runtime_rows,
    CASE
        WHEN COUNT(*) = 1
         AND COALESCE(SUM(
             User = 'fyp_user'
             AND Host = 'localhost'
             AND plugin = 'caching_sha2_password'
             AND authentication_string <> ''
             AND ssl_type <> ''
             AND account_locked = 'N'
             AND password_expired = 'N'
         ), 0) = 1
        THEN 'OK'
        ELSE 'REVIEW'
    END AS account_set_status
FROM mysql.user
WHERE User IN ('fyp_user', 'fyp_migrator');

-- Global static privileges. Expected: no rows after excluding informational
-- USAGE, which represents the absence of a global privilege.
SELECT
    GRANTEE,
    PRIVILEGE_TYPE,
    IS_GRANTABLE
FROM information_schema.USER_PRIVILEGES
WHERE SUBSTRING_INDEX(GRANTEE, '@', 1)
      IN (QUOTE('fyp_user'), QUOTE('fyp_migrator'))
  AND (PRIVILEGE_TYPE <> 'USAGE' OR IS_GRANTABLE <> 'NO')
ORDER BY GRANTEE, PRIVILEGE_TYPE;

-- Dynamic global privileges live in mysql.global_grants rather than
-- information_schema.USER_PRIVILEGES. Expected: no rows.
SELECT
    USER AS account_name,
    HOST AS source_host,
    PRIV AS dynamic_privilege,
    WITH_GRANT_OPTION
FROM mysql.global_grants
WHERE USER IN ('fyp_user', 'fyp_migrator')
ORDER BY USER, HOST, PRIV;

-- Schema-level grants for the runtime identity or retired migrator identity.
-- Expected: no rows. Runtime access is granted per table by 02-schema.sql.
SELECT
    GRANTEE,
    TABLE_SCHEMA AS database_name,
    PRIVILEGE_TYPE,
    IS_GRANTABLE
FROM information_schema.SCHEMA_PRIVILEGES
WHERE SUBSTRING_INDEX(GRANTEE, '@', 1)
      IN (QUOTE('fyp_user'), QUOTE('fyp_migrator'))
ORDER BY GRANTEE, TABLE_SCHEMA, PRIVILEGE_TYPE;

-- All table-level grants for the runtime or retired migrator identity. The raw
-- evidence is followed by a symmetric difference against the exact expected
-- runtime grants; that second result must return no rows.
SELECT
    GRANTEE,
    TABLE_SCHEMA AS database_name,
    TABLE_NAME AS table_name,
    PRIVILEGE_TYPE,
    IS_GRANTABLE
FROM information_schema.TABLE_PRIVILEGES
WHERE SUBSTRING_INDEX(GRANTEE, '@', 1)
      IN (QUOTE('fyp_user'), QUOTE('fyp_migrator'))
ORDER BY GRANTEE, TABLE_SCHEMA, TABLE_NAME, PRIVILEGE_TYPE;

WITH
crud_tables AS (
    SELECT 'auth_login_throttles' AS table_name
    UNION ALL SELECT 'email_verification_codes'
    UNION ALL SELECT 'encrypted_private_key_bundles'
    UNION ALL SELECT 'file_access_grants'
    UNION ALL SELECT 'file_folders'
    UNION ALL SELECT 'file_key_wrappings'
    UNION ALL SELECT 'files'
    UNION ALL SELECT 'integrity_checks'
    UNION ALL SELECT 'recovery_keys'
    UNION ALL SELECT 'recovery_requests'
    UNION ALL SELECT 'session_refresh_tokens'
    UNION ALL SELECT 'user_keys'
    UNION ALL SELECT 'user_key_protection_profiles'
    UNION ALL SELECT 'user_sessions'
    UNION ALL SELECT 'users'
),
crud_privileges AS (
    SELECT 'SELECT' AS privilege_type
    UNION ALL SELECT 'INSERT'
    UNION ALL SELECT 'UPDATE'
    UNION ALL SELECT 'DELETE'
),
expected_table_grants AS (
    SELECT
        CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')) AS grantee,
        'fyp_secure_file_platform' AS database_name,
        crud_tables.table_name,
        crud_privileges.privilege_type,
        'NO' AS is_grantable
    FROM crud_tables
    CROSS JOIN crud_privileges
    UNION ALL
    SELECT CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')),
           'fyp_secure_file_platform', 'audit_logs', 'SELECT', 'NO'
    UNION ALL
    SELECT CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')),
           'fyp_secure_file_platform', 'audit_logs', 'INSERT', 'NO'
    UNION ALL
    SELECT CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')),
           'fyp_secure_file_platform', 'audit_chain_heads', 'SELECT', 'NO'
),
actual_table_grants AS (
    SELECT
        GRANTEE AS grantee,
        TABLE_SCHEMA AS database_name,
        TABLE_NAME AS table_name,
        PRIVILEGE_TYPE AS privilege_type,
        IS_GRANTABLE AS is_grantable
    FROM information_schema.TABLE_PRIVILEGES
    WHERE SUBSTRING_INDEX(GRANTEE, '@', 1)
          IN (QUOTE('fyp_user'), QUOTE('fyp_migrator'))
)
SELECT
    'MISSING' AS deviation,
    expected.grantee,
    expected.database_name,
    expected.table_name,
    expected.privilege_type,
    expected.is_grantable
FROM expected_table_grants AS expected
LEFT JOIN actual_table_grants AS actual
  ON actual.grantee = expected.grantee
 AND actual.database_name = expected.database_name
 AND actual.table_name = expected.table_name
 AND actual.privilege_type = expected.privilege_type
 AND actual.is_grantable = expected.is_grantable
WHERE actual.grantee IS NULL
UNION ALL
SELECT
    'UNEXPECTED' AS deviation,
    actual.grantee,
    actual.database_name,
    actual.table_name,
    actual.privilege_type,
    actual.is_grantable
FROM actual_table_grants AS actual
LEFT JOIN expected_table_grants AS expected
  ON expected.grantee = actual.grantee
 AND expected.database_name = actual.database_name
 AND expected.table_name = actual.table_name
 AND expected.privilege_type = actual.privilege_type
 AND expected.is_grantable = actual.is_grantable
WHERE expected.grantee IS NULL
ORDER BY grantee, database_name, table_name, privilege_type, deviation;

-- The runtime may advance only the mutable audit-chain-head fields. In
-- particular it must not be able to change schema_revision. The symmetric
-- difference below must return no rows.
WITH
expected_column_grants AS (
    SELECT CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')) AS grantee,
           'fyp_secure_file_platform' AS database_name,
           'audit_chain_heads' AS table_name,
           'last_log_id' AS column_name,
           'UPDATE' AS privilege_type,
           'NO' AS is_grantable
    UNION ALL
    SELECT CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')),
           'fyp_secure_file_platform', 'audit_chain_heads',
           'current_hash', 'UPDATE', 'NO'
    UNION ALL
    SELECT CONCAT(QUOTE('fyp_user'), '@', QUOTE('localhost')),
           'fyp_secure_file_platform', 'audit_chain_heads',
           'updated_at', 'UPDATE', 'NO'
),
actual_column_grants AS (
    SELECT GRANTEE AS grantee,
           TABLE_SCHEMA AS database_name,
           TABLE_NAME AS table_name,
           COLUMN_NAME AS column_name,
           PRIVILEGE_TYPE AS privilege_type,
           IS_GRANTABLE AS is_grantable
    FROM information_schema.COLUMN_PRIVILEGES
    WHERE SUBSTRING_INDEX(GRANTEE, '@', 1)
          IN (QUOTE('fyp_user'), QUOTE('fyp_migrator'))
)
SELECT 'MISSING' AS deviation,
       expected.grantee,
       expected.database_name,
       expected.table_name,
       expected.column_name,
       expected.privilege_type,
       expected.is_grantable
FROM expected_column_grants AS expected
LEFT JOIN actual_column_grants AS actual
  ON actual.grantee = expected.grantee
 AND actual.database_name = expected.database_name
 AND actual.table_name = expected.table_name
 AND actual.column_name = expected.column_name
 AND actual.privilege_type = expected.privilege_type
 AND actual.is_grantable = expected.is_grantable
WHERE actual.grantee IS NULL
UNION ALL
SELECT 'UNEXPECTED' AS deviation,
       actual.grantee,
       actual.database_name,
       actual.table_name,
       actual.column_name,
       actual.privilege_type,
       actual.is_grantable
FROM actual_column_grants AS actual
LEFT JOIN expected_column_grants AS expected
  ON expected.grantee = actual.grantee
 AND expected.database_name = actual.database_name
 AND expected.table_name = actual.table_name
 AND expected.column_name = actual.column_name
 AND expected.privilege_type = actual.privilege_type
 AND expected.is_grantable = actual.is_grantable
WHERE expected.grantee IS NULL
ORDER BY grantee, database_name, table_name, column_name, privilege_type, deviation;

-- Stored procedure/function grants. Expected: no rows.
SELECT
    User AS account_name,
    Host AS source_host,
    Db AS database_name,
    Routine_name AS routine_name,
    Routine_type AS routine_type,
    Proc_priv AS privileges,
    Grantor AS granted_by
FROM mysql.procs_priv
WHERE User IN ('fyp_user', 'fyp_migrator')
ORDER BY User, Host, Db, Routine_name, Routine_type;

-- Mandatory roles apply to every account without appearing in role_edges.
-- Expected: an empty value and status OK.
SELECT
    @@GLOBAL.mandatory_roles AS mandatory_roles,
    CASE
        WHEN COALESCE(@@GLOBAL.mandatory_roles, '') = '' THEN 'OK'
        ELSE 'REVIEW'
    END AS mandatory_roles_status;

-- Ordinary role edges. MySQL stores the grantee account in FROM_* and the
-- granted role in TO_*. Filtering both directions also catches either
-- the application identity being reused as a role. Expected: no rows.
SELECT
    FROM_USER AS grantee_account,
    FROM_HOST AS grantee_host,
    TO_USER AS granted_role,
    TO_HOST AS granted_role_host,
    WITH_ADMIN_OPTION
FROM mysql.role_edges
WHERE FROM_USER IN ('fyp_user', 'fyp_migrator')
   OR TO_USER IN ('fyp_user', 'fyp_migrator')
ORDER BY FROM_USER, FROM_HOST, TO_USER, TO_HOST;

-- Default-role assignments, including either identity being reused as a
-- default role for another account. Expected: no rows.
SELECT
    User AS account_name,
    Host AS source_host,
    Default_role_user AS default_role,
    Default_role_host AS default_role_host
FROM mysql.default_roles
WHERE User IN ('fyp_user', 'fyp_migrator')
   OR Default_role_user IN ('fyp_user', 'fyp_migrator')
ORDER BY User, Host, Default_role_user, Default_role_host;

-- Proxy relationships in either direction. User/Host is the proxy account;
-- Proxied_user/Proxied_host is the impersonated account. Expected: no rows.
SELECT
    User AS proxy_account,
    Host AS proxy_host,
    Proxied_user AS proxied_account,
    Proxied_host AS proxied_host,
    With_grant AS is_grantable,
    Grantor AS granted_by
FROM mysql.proxies_priv
WHERE User IN ('fyp_user', 'fyp_migrator')
   OR Proxied_user IN ('fyp_user', 'fyp_migrator')
ORDER BY User, Host, Proxied_user, Proxied_host;

-- Exact persistent table inventory produced by 02-schema.sql. The symmetric
-- difference must return no rows; views and unexpected tables are deviations.
WITH
expected_table_names AS (
    SELECT 'alembic_version' AS table_name
    UNION ALL SELECT 'audit_chain_heads'
    UNION ALL SELECT 'audit_logs'
    UNION ALL SELECT 'auth_login_throttles'
    UNION ALL SELECT 'email_verification_codes'
    UNION ALL SELECT 'encrypted_private_key_bundles'
    UNION ALL SELECT 'file_access_grants'
    UNION ALL SELECT 'file_folders'
    UNION ALL SELECT 'file_key_wrappings'
    UNION ALL SELECT 'files'
    UNION ALL SELECT 'integrity_checks'
    UNION ALL SELECT 'recovery_keys'
    UNION ALL SELECT 'recovery_requests'
    UNION ALL SELECT 'session_refresh_tokens'
    UNION ALL SELECT 'user_keys'
    UNION ALL SELECT 'user_key_protection_profiles'
    UNION ALL SELECT 'user_sessions'
    UNION ALL SELECT 'users'
),
expected_tables AS (
    SELECT table_name,
           'BASE TABLE' AS table_type,
           'InnoDB' AS storage_engine,
           'utf8mb4_unicode_ci' AS table_collation
    FROM expected_table_names
),
actual_tables AS (
    SELECT TABLE_NAME AS table_name,
           TABLE_TYPE AS table_type,
           ENGINE AS storage_engine,
           TABLE_COLLATION AS table_collation
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = 'fyp_secure_file_platform'
)
SELECT
    'MISSING' AS deviation,
    expected.table_name,
    expected.table_type,
    expected.storage_engine,
    expected.table_collation
FROM expected_tables AS expected
LEFT JOIN actual_tables AS actual
 ON actual.table_name = expected.table_name
 AND actual.table_type = expected.table_type
 AND actual.storage_engine = expected.storage_engine
 AND actual.table_collation = expected.table_collation
WHERE actual.table_name IS NULL
UNION ALL
SELECT
    'UNEXPECTED' AS deviation,
    actual.table_name,
    actual.table_type,
    actual.storage_engine,
    actual.table_collation
FROM actual_tables AS actual
LEFT JOIN expected_tables AS expected
 ON expected.table_name = actual.table_name
 AND expected.table_type = actual.table_type
 AND expected.storage_engine = actual.storage_engine
 AND expected.table_collation = actual.table_collation
WHERE expected.table_name IS NULL
ORDER BY table_name, deviation;

-- The install starts with the predecessor default and restores final-schema
-- parity immediately before publishing the singleton as 0004. Expected: OK.
SELECT
    CASE
        WHEN COUNT(*) = 1
         AND MAX(COLUMN_DEFAULT) = '0011_must_change_password'
        THEN 'OK'
        ELSE 'REVIEW'
    END AS readiness_marker_default_status
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'fyp_secure_file_platform'
  AND TABLE_NAME = 'audit_chain_heads'
  AND COLUMN_NAME = 'schema_revision';

-- Structural totals for the tracked final schema. The non-unique index total
-- includes MySQL's implicit FK-supporting index on audit_chain_heads.last_log_id.
-- Expected: status OK.
SELECT
    (SELECT COUNT(*)
     FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = 'fyp_secure_file_platform') AS column_count,
    (SELECT COUNT(*)
     FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
       AND CONSTRAINT_TYPE = 'PRIMARY KEY') AS primary_key_count,
    (SELECT COUNT(*)
     FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
       AND CONSTRAINT_TYPE = 'UNIQUE') AS unique_constraint_count,
    (SELECT COUNT(*)
     FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
       AND CONSTRAINT_TYPE = 'FOREIGN KEY') AS foreign_key_count,
    (SELECT COUNT(*)
     FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
       AND CONSTRAINT_TYPE = 'CHECK') AS check_constraint_count,
    (SELECT COUNT(DISTINCT TABLE_NAME, INDEX_NAME)
     FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = 'fyp_secure_file_platform'
       AND INDEX_NAME <> 'PRIMARY'
       AND NON_UNIQUE = 1) AS nonunique_index_count,
    CASE
        WHEN (SELECT COUNT(*)
              FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'fyp_secure_file_platform') = 215
         AND (SELECT COUNT(*)
              FROM information_schema.TABLE_CONSTRAINTS
              WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
                AND CONSTRAINT_TYPE = 'PRIMARY KEY') = 18
         AND (SELECT COUNT(*)
              FROM information_schema.TABLE_CONSTRAINTS
              WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
                AND CONSTRAINT_TYPE = 'UNIQUE') = 25
         AND (SELECT COUNT(*)
              FROM information_schema.TABLE_CONSTRAINTS
              WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
                AND CONSTRAINT_TYPE = 'FOREIGN KEY') = 29
         AND (SELECT COUNT(*)
              FROM information_schema.TABLE_CONSTRAINTS
              WHERE CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
                AND CONSTRAINT_TYPE = 'CHECK') = 37
         AND (SELECT COUNT(DISTINCT TABLE_NAME, INDEX_NAME)
              FROM information_schema.STATISTICS
              WHERE TABLE_SCHEMA = 'fyp_secure_file_platform'
                AND INDEX_NAME <> 'PRIMARY'
                AND NON_UNIQUE = 1) = 67
        THEN 'OK'
        ELSE 'REVIEW'
    END AS schema_structure_status;

-- Security-critical FK definitions. The symmetric difference must return no
-- rows, including exact child/parent columns and delete/update actions.
WITH
expected_critical_fks AS (
    SELECT 'fk_audit_logs_actor_user' AS constraint_name,
           'audit_logs' AS table_name,
           'actor_user_id' AS column_name,
           'users' AS referenced_table_name,
           'id' AS referenced_column_name,
           'RESTRICT' AS delete_rule,
           'RESTRICT' AS update_rule
    UNION ALL SELECT 'fk_audit_logs_target_user', 'audit_logs',
                     'target_user_id', 'users', 'id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'fk_audit_chain_heads_last_log', 'audit_chain_heads',
                     'last_log_id', 'audit_logs', 'id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'fk_user_sessions_user', 'user_sessions',
                     'user_id', 'users', 'id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_session_refresh_tokens_session', 'session_refresh_tokens',
                     'session_id', 'user_sessions', 'id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_email_verification_codes_user', 'email_verification_codes',
                     'user_id', 'users', 'id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_user_key_protection_profiles_user',
                     'user_key_protection_profiles', 'user_id', 'users', 'id',
                     'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_encrypted_private_key_bundles_profile',
                     'encrypted_private_key_bundles', 'user_id',
                     'user_key_protection_profiles', 'user_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_encrypted_private_key_bundles_user_key_owner',
                     'encrypted_private_key_bundles', 'user_key_id',
                     'user_keys', 'id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_encrypted_private_key_bundles_user_key_owner',
                     'encrypted_private_key_bundles', 'user_id',
                     'user_keys', 'user_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'fk_file_key_wrappings_user_key_owner',
                     'file_key_wrappings', 'user_key_id', 'user_keys', 'id',
                     'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'fk_file_key_wrappings_user_key_owner',
                     'file_key_wrappings', 'recipient_user_id',
                     'user_keys', 'user_id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'fk_file_key_wrappings_recovery_key',
                     'file_key_wrappings', 'recovery_key_id',
                     'recovery_keys', 'id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'fk_integrity_checks_file', 'integrity_checks',
                     'file_id', 'files', 'id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'fk_recovery_requests_target_key_owner',
                     'recovery_requests', 'target_user_key_id',
                     'user_keys', 'id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'fk_recovery_requests_target_key_owner',
                     'recovery_requests', 'requested_by',
                     'user_keys', 'user_id', 'RESTRICT', 'RESTRICT'
),
actual_critical_fks AS (
    SELECT
        kcu.CONSTRAINT_NAME AS constraint_name,
        kcu.TABLE_NAME AS table_name,
        kcu.COLUMN_NAME AS column_name,
        kcu.REFERENCED_TABLE_NAME AS referenced_table_name,
        kcu.REFERENCED_COLUMN_NAME AS referenced_column_name,
        rc.DELETE_RULE AS delete_rule,
        rc.UPDATE_RULE AS update_rule
    FROM information_schema.KEY_COLUMN_USAGE AS kcu
    JOIN information_schema.REFERENTIAL_CONSTRAINTS AS rc
      ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
     AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
     AND rc.TABLE_NAME = kcu.TABLE_NAME
    WHERE kcu.CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
      AND kcu.CONSTRAINT_NAME IN (
          'fk_audit_logs_actor_user',
          'fk_audit_logs_target_user',
          'fk_audit_chain_heads_last_log',
          'fk_user_sessions_user',
          'fk_session_refresh_tokens_session',
          'fk_email_verification_codes_user',
          'fk_user_key_protection_profiles_user',
          'fk_encrypted_private_key_bundles_profile',
          'fk_encrypted_private_key_bundles_user_key_owner',
          'fk_file_key_wrappings_user_key_owner',
          'fk_file_key_wrappings_recovery_key',
          'fk_integrity_checks_file',
          'fk_recovery_requests_target_key_owner'
      )
)
SELECT 'MISSING' AS deviation, expected.*
FROM expected_critical_fks AS expected
LEFT JOIN actual_critical_fks AS actual
  ON actual.constraint_name = expected.constraint_name
 AND actual.table_name = expected.table_name
 AND actual.column_name = expected.column_name
 AND actual.referenced_table_name = expected.referenced_table_name
 AND actual.referenced_column_name = expected.referenced_column_name
 AND actual.delete_rule = expected.delete_rule
 AND actual.update_rule = expected.update_rule
WHERE actual.constraint_name IS NULL
UNION ALL
SELECT 'UNEXPECTED' AS deviation, actual.*
FROM actual_critical_fks AS actual
LEFT JOIN expected_critical_fks AS expected
  ON expected.constraint_name = actual.constraint_name
 AND expected.table_name = actual.table_name
 AND expected.column_name = actual.column_name
 AND expected.referenced_table_name = actual.referenced_table_name
 AND expected.referenced_column_name = actual.referenced_column_name
 AND expected.delete_rule = actual.delete_rule
 AND expected.update_rule = actual.update_rule
WHERE expected.constraint_name IS NULL
ORDER BY constraint_name, deviation;

-- Security-critical CHECK definitions. MySQL 8.4 persists OCTET_LENGTH as its
-- LENGTH synonym and may add character-set introducers plus escaped quotes to
-- string literals in information_schema.CHECK_CONSTRAINTS. Normalize only
-- those server-rendering differences, identifier quoting, whitespace, and
-- outer parentheses. Expected: no deviation rows.
WITH
expected_critical_checks AS (
    SELECT 'ck_audit_chain_heads_singleton' AS constraint_name,
           'audit_chain_heads' AS table_name,
           'id=1' AS normalized_clause
    UNION ALL SELECT 'ck_user_sessions_access_before_absolute', 'user_sessions',
                     'access_expires_at<=absolute_expires_at'
    UNION ALL SELECT 'ck_session_refresh_tokens_expiry_after_creation',
                     'session_refresh_tokens', 'expires_at>created_at'
    UNION ALL SELECT 'ck_email_verification_codes_expiry_after_creation',
                     'email_verification_codes', 'expires_at>created_at'
    UNION ALL SELECT 'ck_email_verification_codes_attempts',
                     'email_verification_codes',
                     'max_attempts>=1andattempt_count<=max_attempts'
    UNION ALL SELECT 'ck_email_verification_codes_consumed_at',
                     'email_verification_codes',
                     "status='consumed'andconsumed_atisnotnullorstatus<>'consumed'andconsumed_atisnull"
    UNION ALL SELECT 'ck_file_key_wrappings_recipient_shape',
                     'file_key_wrappings',
                     "recipient_type='user'andrecipient_user_idisnotnullanduser_key_idisnotnullandrecovery_key_idisnullorrecipient_type='recovery'andrecipient_user_idisnullanduser_key_idisnullandrecovery_key_idisnotnull"
    UNION ALL SELECT 'ck_user_key_protection_profiles_amk_envelope',
                     'user_key_protection_profiles',
                     "amk_wrapping_algorithm='aes-256-gcm'andlengthwrapped_amk=32andlengthamk_nonce=12andlengthamk_auth_tag=16"
    UNION ALL SELECT 'ck_encrypted_private_key_bundles_envelope',
                     'encrypted_private_key_bundles',
                     'lengthderivation_saltbetween16and32andlengthnonce=12andlengthauth_tag=16andlengthencrypted_private_keybetween1and16384'
    UNION ALL SELECT 'ck_recovery_requests_maker_checker',
                     'recovery_requests', 'approved_byisnullorapproved_by<>requested_by'
),
actual_critical_checks AS (
    SELECT
        tc.CONSTRAINT_NAME AS constraint_name,
        tc.TABLE_NAME AS table_name,
        REPLACE(REPLACE(REPLACE(
            LOWER(REPLACE(REPLACE(REPLACE(REPLACE(
                cc.CHECK_CLAUSE, '`', ''), ' ', ''), '(', ''), ')', '')),
            '_utf8mb4', ''), '_latin1', ''), CHAR(92), '')
            AS normalized_clause
    FROM information_schema.TABLE_CONSTRAINTS AS tc
    JOIN information_schema.CHECK_CONSTRAINTS AS cc
      ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
     AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_SCHEMA = 'fyp_secure_file_platform'
      AND tc.CONSTRAINT_TYPE = 'CHECK'
      AND tc.CONSTRAINT_NAME IN (
          'ck_audit_chain_heads_singleton',
          'ck_user_sessions_access_before_absolute',
          'ck_session_refresh_tokens_expiry_after_creation',
          'ck_email_verification_codes_expiry_after_creation',
          'ck_email_verification_codes_attempts',
          'ck_email_verification_codes_consumed_at',
          'ck_file_key_wrappings_recipient_shape',
          'ck_user_key_protection_profiles_amk_envelope',
          'ck_encrypted_private_key_bundles_envelope',
          'ck_recovery_requests_maker_checker'
      )
)
SELECT 'MISSING' AS deviation, expected.*
FROM expected_critical_checks AS expected
LEFT JOIN actual_critical_checks AS actual
  ON actual.constraint_name = expected.constraint_name
 AND actual.table_name = expected.table_name
 AND actual.normalized_clause = expected.normalized_clause
WHERE actual.constraint_name IS NULL
UNION ALL
SELECT 'UNEXPECTED' AS deviation, actual.*
FROM actual_critical_checks AS actual
LEFT JOIN expected_critical_checks AS expected
  ON expected.constraint_name = actual.constraint_name
 AND expected.table_name = actual.table_name
 AND expected.normalized_clause = actual.normalized_clause
WHERE expected.constraint_name IS NULL
ORDER BY constraint_name, deviation;

-- Critical composite-index definitions. Expected: no deviation rows.
WITH
expected_critical_indexes AS (
    SELECT 'audit_logs' AS table_name,
           'idx_audit_logs_resource' AS index_name,
           'resource_type,resource_id' AS ordered_columns
    UNION ALL SELECT 'user_sessions', 'idx_user_sessions_user_status',
                     'user_id,status'
    UNION ALL SELECT 'user_sessions', 'idx_user_sessions_status_access_expires',
                     'status,access_expires_at'
    UNION ALL SELECT 'user_sessions', 'idx_user_sessions_status_absolute_expires',
                     'status,absolute_expires_at'
    UNION ALL SELECT 'file_key_wrappings',
                     'idx_file_key_wrappings_recipient_status_file_key',
                     'recipient_user_id,status,file_id,user_key_id'
    UNION ALL SELECT 'encrypted_private_key_bundles',
                     'idx_encrypted_private_key_bundles_user_key_owner',
                     'user_key_id,user_id'
    UNION ALL SELECT 'recovery_requests',
                     'idx_recovery_requests_target_key_owner',
                     'target_user_key_id,requested_by'
),
actual_critical_indexes AS (
    SELECT
        TABLE_NAME AS table_name,
        INDEX_NAME AS index_name,
        GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',')
            AS ordered_columns
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'fyp_secure_file_platform'
      AND INDEX_NAME IN (
          'idx_audit_logs_resource',
          'idx_user_sessions_user_status',
          'idx_user_sessions_status_access_expires',
          'idx_user_sessions_status_absolute_expires',
          'idx_file_key_wrappings_recipient_status_file_key',
          'idx_encrypted_private_key_bundles_user_key_owner',
          'idx_recovery_requests_target_key_owner'
      )
    GROUP BY TABLE_NAME, INDEX_NAME
)
SELECT 'MISSING' AS deviation, expected.*
FROM expected_critical_indexes AS expected
LEFT JOIN actual_critical_indexes AS actual
  ON actual.table_name = expected.table_name
 AND actual.index_name = expected.index_name
 AND actual.ordered_columns = expected.ordered_columns
WHERE actual.index_name IS NULL
UNION ALL
SELECT 'UNEXPECTED' AS deviation, actual.*
FROM actual_critical_indexes AS actual
LEFT JOIN expected_critical_indexes AS expected
  ON expected.table_name = actual.table_name
 AND expected.index_name = actual.index_name
 AND expected.ordered_columns = actual.ordered_columns
WHERE expected.index_name IS NULL
ORDER BY table_name, index_name, deviation;

-- Expected: exactly one compatibility marker for the SQL schema release.
SELECT
    COUNT(*) AS alembic_revision_rows,
    GROUP_CONCAT(version_num ORDER BY version_num) AS alembic_revisions,
    CASE
        WHEN COUNT(*) = 1
         AND MAX(version_num) = '0011_must_change_password'
        THEN 'OK'
        ELSE 'REVIEW'
    END AS schema_compatibility_status
FROM `fyp_secure_file_platform`.alembic_version;

-- A fresh installation has no audit rows. An already-running deployment may
-- legitimately contain rows; the chain-head query below must still prove that
-- the singleton points at the newest row with the same hash.
SELECT
    COUNT(*) AS audit_log_rows,
    CASE WHEN COUNT(*) = 0 THEN 'OK' ELSE 'LIVE_DATA' END AS audit_log_status
FROM `fyp_secure_file_platform`.audit_logs;

-- Expected: either the fresh-install genesis singleton, or one live singleton
-- whose last_log_id is the newest audit row and whose hash matches that row.
SELECT
    COUNT(head.id) AS audit_chain_head_rows,
    COALESCE(SUM(
        head.id = 1
        AND audit_state.audit_log_rows = 0
        AND head.last_log_id IS NULL
        AND head.current_hash =
            '0000000000000000000000000000000000000000000000000000000000000000'
        AND head.schema_revision = '0011_must_change_password'
    ), 0) AS genesis_rows,
    COALESCE(SUM(
        head.id = 1
        AND audit_state.audit_log_rows > 0
        AND head.last_log_id = audit_state.max_log_id
        AND last_log.current_hash = head.current_hash
        AND head.schema_revision = '0011_must_change_password'
    ), 0) AS live_rows,
    CASE
        WHEN COUNT(head.id) = 1
         AND COALESCE(SUM(
             head.id = 1
             AND audit_state.audit_log_rows = 0
             AND head.last_log_id IS NULL
             AND head.current_hash =
                 '0000000000000000000000000000000000000000000000000000000000000000'
             AND head.schema_revision = '0011_must_change_password'
         ), 0) = 1
        THEN 'OK'
        WHEN COUNT(head.id) = 1
         AND COALESCE(SUM(
             head.id = 1
             AND audit_state.audit_log_rows > 0
             AND head.last_log_id = audit_state.max_log_id
             AND last_log.current_hash = head.current_hash
             AND head.schema_revision = '0011_must_change_password'
         ), 0) = 1
        THEN 'LIVE_DATA'
        ELSE 'REVIEW'
    END AS audit_singleton_status
FROM `fyp_secure_file_platform`.audit_chain_heads AS head
LEFT JOIN `fyp_secure_file_platform`.audit_logs AS last_log
  ON last_log.id = head.last_log_id
CROSS JOIN (
    SELECT
        COUNT(*) AS audit_log_rows,
        MAX(id) AS max_log_id
    FROM `fyp_secure_file_platform`.audit_logs
) AS audit_state;
