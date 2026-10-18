-- MySQL 8.4 least-privilege backup account (issue #56).
--
-- Run this file as MySQL root/administrator, after 01-provision.sql and
-- 02-schema.sql, on the database server. It is separate from 02-schema.sql on
-- purpose: 02-schema.sql is an empty-database installer that must never be
-- re-run, while this file can be applied to an already-live deployment and
-- re-applied safely (CREATE USER IF NOT EXISTS and GRANT are both idempotent).
--
--     sudo mysql < database/mysql/04-backup-account.sql
--
-- MySQL generates the password and returns it in the CREATE USER result set.
-- Capture it straight into the backup host's secret store (the file named by
-- BACKUP_DB_DEFAULTS_FILE in docs/BACKUP_AND_RECOVERY.md); never put it in this
-- file, shell history, logs, or version control. If the account already
-- existed, SHOW WARNINGS reports it and the password is left unchanged.
--
-- What the account can do: read every table of the application database, which
-- is all `mysqldump --single-transaction --no-tablespaces --skip-triggers`
-- needs. Every application table is InnoDB, so the dump takes one consistent
-- snapshot without LOCK TABLES, RELOAD, FLUSH_TABLES, or PROCESS.
--
-- What it cannot do: write, lock, run DDL, grant, read any other database, or
-- open more than two connections. backend/scripts/check_runtime_grants.py
-- connects as this account in CI and proves each of those refusals.
--
-- The grant is database-level rather than per table, unlike the runtime grants
-- in 02-schema.sql. mysqldump silently leaves out tables it cannot see, so a
-- per-table list would quietly drop any table a future release adds from every
-- backup. A read-only grant on a new table is the smaller risk.
--
-- For a remote backup host, replace the localhost account-host literal with the
-- narrowest host pattern the network allows, in a protected copy kept out of
-- version control, exactly as for the other three files.

CREATE USER IF NOT EXISTS 'fyp_backup_user'@'localhost'
    IDENTIFIED WITH caching_sha2_password BY RANDOM PASSWORD
    REQUIRE SSL
    WITH MAX_USER_CONNECTIONS 2;

SHOW WARNINGS;

GRANT SELECT ON `fyp_secure_file_platform`.* TO 'fyp_backup_user'@'localhost';

-- Expected: exactly one database-level row, SELECT on fyp_secure_file_platform,
-- plus the USAGE row MySQL always reports. Anything else is a deviation.
SHOW GRANTS FOR 'fyp_backup_user'@'localhost';
