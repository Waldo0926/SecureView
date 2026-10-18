-- MySQL 8.4 database and account provisioning template.
--
-- Run this file once as MySQL root/administrator. From the repository root on
-- the database server, either execute it directly:
--
--     sudo mysql < database/mysql/01-provision.sql
--     mysql --user=root --password < database/mysql/01-provision.sql
--
-- Never put the root password directly on the command line, never use an
-- interactive SOURCE command, and never use the mysql client's --force option.
--
-- The account host defaults to localhost for a same-host deployment. If the
-- application connects remotely, copy all three deployment SQL files outside
-- the repository. Replace every localhost account-host literal consistently
-- in all three protected copies, using the
-- narrowest source-host pattern allowed by the deployment network. Otherwise
-- the exact checks in 03-verify.sql intentionally report a mismatch. Keep all
-- edited copies out of version control.
--
-- For newly created accounts, MySQL generates the passwords and returns them
-- in the CREATE USER result sets. Capture those results directly into the
-- deployment secret store;
-- do not put passwords in this file, shell history, logs, or version control.
--
-- CREATE USER IF NOT EXISTS does not alter an existing account's password,
-- authentication, TLS policy, or prior grants. SHOW WARNINGS makes an
-- existing-account collision visible. If the account already existed, audit
-- it with 03-verify.sql and explicitly correct anything unexpected before
-- deployment.
--
-- This file creates no application tables. Run 02-schema.sql next, as the
-- same root/administrator identity, to create the complete application schema.

CREATE DATABASE IF NOT EXISTS `fyp_secure_file_platform`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'fyp_user'@'localhost'
    IDENTIFIED WITH caching_sha2_password BY RANDOM PASSWORD
    REQUIRE SSL;

SHOW WARNINGS;

-- Table-scoped runtime grants are installed only after every table exists, at
-- the end of 02-schema.sql. FLUSH PRIVILEGES is neither required nor
-- appropriate after CREATE USER or GRANT.
