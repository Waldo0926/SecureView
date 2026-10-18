# Database Schema and Migration Policy

[English](DATABASE_SCHEMA.md) | [简体中文](DATABASE_SCHEMA.zh-CN.md)

## Source of Truth

SQLAlchemy metadata in `backend/app/models/` and the ordered Alembic revisions in
`backend/migrations/` are the development and CI schema-authoring authority.

Production does not run Alembic. The reviewed delivery artifacts under `database/mysql/`
are derived from that authoring history and are executed by a MySQL root/administrator:

1. `01-provision.sql` creates the database and the TLS-required `fyp_user` runtime account.
2. `02-schema.sql` installs the complete schema on an empty database, seeds the audit-chain
   singleton and compatibility marker, and grants exact table/column-level runtime privileges.
3. `03-verify.sql` reads server, account, grant, schema, marker, and singleton metadata before
   the application starts.

CI must compare the production schema artifact with the current Alembic head and ORM
metadata. A model or revision change is incomplete until the reviewed SQL artifact,
verification expectations, and parity tests change with it.

The current ordered history is:

1. `0001_initial_schema`: initial users, keys, sessions, files, access, integrity, audit,
   and recovery schema.
2. `0002_auth_identity_sessions`: public user/session UUIDs, access-session evolution,
   one-time refresh generations, persistent authentication throttles, password-change time,
   and the singleton audit-chain head.
3. `0003_client_key_custody`: public user/recovery key UUIDs and key sizes, client-wrapped
   account-key protection profiles, encrypted private-key bundles, versioned file envelopes,
   optimistic revisions, strengthened grant/wrapping ownership constraints, and the expanded
   recovery-request state needed for offline DEK rewrapping.
4. `0004_email_verification_codes`: the `email_verification_codes` challenge table for
   registration and password reset, and four additional `auth_login_throttles` scopes that
   rate limit code sending and code checking per address and per IP.
5. `0005_selectable_aes_key_length`: file content may also use AES-128-GCM or AES-192-GCM.
6. `0006_chacha20_poly1305`: adds ChaCha20-Poly1305 and makes the suite-name check
   case-sensitive (`utf8mb4_bin`).
7. `0007_file_folders`: the `file_folders` table and `files.folder_id` for an owner's folders.
8. `0008_avatars`: optional validated avatar metadata on `users` (the image bytes stay on disk,
   outside the encrypted-object root).
9. `0009_more_aead_suites`: adds AES-256-GCM-SIV and XChaCha20-Poly1305; the nonce-length check
   becomes per-suite (24 bytes for XChaCha20-Poly1305, 12 for every other suite).
10. `0010_shared_file_folders`: `file_access_grants.folder_id`, so a recipient can file a shared
    file into one of their own folders without moving the owner's placement.
11. `0011_must_change_password`: `users.must_change_password` (`BOOL NOT NULL DEFAULT 0`), set by an
    administrator's login-password reset and cleared when the holder sets a password of their
    own. Login and `/auth/me` report it; the frontend keeps the holder on Settings while it is
    true, and since 2026-10-09 the API refuses every authenticated route except `/auth/me`,
    change password and logout with `403 password_change_required`.

Revisions 0005, 0006 and 0009 refuse to downgrade while any file uses a suite they added,
rather than delete intact files. `database/mysql/04-backup-account.sql` is a separate,
re-runnable script that creates the least-privilege backup account (see
[BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md)).

The historical `docs/init.sql` development bootstrap has been deleted. A database previously
created from it is not automatically managed. The backend must not call
`Base.metadata.create_all()` at startup. `02-schema.sql` is the sole reviewed production
empty-database installer, not an application-startup hook.

## Development and CI Authoring Workflow

Run these commands from `backend/` only against disposable or explicitly Alembic-managed
development/CI databases:

```bash
alembic upgrade head
alembic current
alembic check
```

After intentionally changing an ORM model:

```bash
alembic revision --autogenerate -m "describe the schema change"
```

Always review generated revisions. Autogenerate cannot understand data migrations,
application invariants, safe column backfills, or deployment order. A revision must be
forward-safe for existing data. Revisions `0002_auth_identity_sessions` and
`0003_client_key_custody` are intentionally forward-only. Revision `0003` runs legacy-data
preflight checks before permanent DDL and adds `audit_chain_heads.schema_revision` with the
predecessor default `0002_auth_identity_sessions`. Because MySQL DDL commits
statement-by-statement, it publishes `0003_client_key_custody` only as the final migration
statement after all required structures exist, restoring the final 0003 column default just
before that explicit row update. The runtime identity has table-level `SELECT`
and column-level `UPDATE` only for the chain head's mutable hash fields, so it cannot forge
this readiness marker. The migration assigns UUIDs to existing public keys and marks them
`LEGACY_EXTERNAL`; it does not fabricate client-encrypted private-key bundles for those keys.
Restore a backup for rollback, or rebuild a disposable development database.

Revision `0004_email_verification_codes` is reversible, because it only adds a table whose
rows are short-lived challenges and widens an enum. Its downgrade drops the table before
narrowing the enum and lowering the readiness marker: MySQL refuses to drop an index that a
foreign key depends on, so the table must go first, and ordering the marker last keeps a
failed downgrade from advertising a revision the schema no longer matches. Downgrading
discards pending challenges and any throttle rows in the four verification scopes.

For a new staging or production database, follow [DEPLOYMENT.md](DEPLOYMENT.md): the same
root/administrator runs `01-provision.sql`, `02-schema.sql`, and the read-only
`03-verify.sql` in fail-fast batch mode. Only then does the application start as `fyp_user`.
There is no production `fyp_migrator`, no temporary switch of application `DB_*` credentials,
and no Python/Alembic command on the database server.

`02-schema.sql` deliberately refuses a non-empty schema and MySQL DDL is not fully
transactional. It must never be used as an upgrade mechanism. Future changes to a non-empty
production database require an immutable, versioned, reviewed DBA SQL upgrade with writer
drain, serialization, bounded waits, a verified restorable backup, explicit preconditions,
and release-specific post-verification. Revisions 0005–0010 reached staging that way: the SQL
is rendered from the revision with `alembic upgrade <previous>:<new> --sql` and applied by hand
before the code that expects it (see
[DEPLOYMENT.md](DEPLOYMENT.md#applying-a-schema-revision-to-a-running-deployment)).

The deleted Python runner previously supplied advisory locking, connectivity retries,
preflight/refusal checks, exact table validation, and backup confirmation. Release
orchestration and operator procedure must provide those controls around the root-executed SQL.

### Adopting a Legacy Development Database

A database created by the historical, now-deleted `docs/init.sql` has application tables but no
`alembic_version` row. For local development, do **not** run `alembic upgrade head` or blindly
stamp it as current:
the new baseline also renames `files.storage_path` to `storage_object_key` and removes the
ambiguous `file_access_grants.permission_level` column.

Migration `0002_auth_identity_sessions` contains safe backfills for a database that already
reached Alembic revision `0001_initial`; it does not adopt an unmanaged legacy schema and
does not make blind stamping safe. It also requires `audit_logs` to be empty: a non-empty
revision-0001 chain needs a reviewed adoption/checkpoint migration because its historical hash
payload and timestamp precision are not losslessly convertible.

- If the legacy development database is disposable and contains no needed data, recreate it
  and then use the normal development Alembic workflow.
- If a development database contains needed data, back it up and write/review a one-time
  adoption migration that performs those transformations before stamping the baseline.
- If any non-empty staging or production database needs to be retained, do not run Alembic or
  `02-schema.sql`; use a separately reviewed, versioned DBA SQL adoption/upgrade procedure.

Any such database remains legacy until it is deliberately recreated as disposable or handled
through a reviewed adoption procedure. No development migration command or production SQL in
this repository silently deletes, stamps, or adopts it.

## Table Groups

| Area | Tables | Purpose |
|---|---|---|
| Identity | `users`, `user_sessions`, `session_refresh_tokens`, `user_keys`, `user_key_protection_profiles`, `encrypted_private_key_bundles` | Accounts, opaque sessions, public-key history, KEK-wrapped AMK profiles, and client-encrypted private-key bundles |
| Identity proof | `email_verification_codes` | One-time registration/password-reset challenges stored only as keyed digests |
| Abuse control | `auth_login_throttles` | HMAC-keyed login, reauthentication, registration, and verification send/check buckets shared across workers |
| Files | `files`, `file_access_grants`, `file_key_wrappings`, `file_folders` | Encrypted-object metadata, logical and cryptographic access, and per-user folders |
| Assurance | `integrity_checks`, `audit_logs`, `audit_chain_heads` | Verification history, security events, and serialized audit-chain append state |
| Recovery | `recovery_keys`, `recovery_requests` | Recovery public keys and maker-checker workflow |

The local encrypted object itself is not stored in MySQL. The `files` row stores an opaque
storage object key; the storage adapter resolves that key inside its configured root.

## Required Invariants

The following are transaction-level invariants and need integration tests even where MySQL
cannot express them cleanly:

1. Public user/session UUIDs are unique; numeric primary and foreign keys never enter API
   DTOs. Raw access and refresh credentials never enter database rows.
2. Each session has one current access hash and monotonically numbered refresh records.
   Refresh `(session_id, generation)` and token hashes are unique. A consumed token cannot
   be accepted again; replay revokes the complete session family.
3. Access expiry is not later than absolute session expiry. Refresh expiry is bounded by the
   same absolute expiry, and revoking a family makes all of its credentials unusable.
4. Authentication throttle keys are HMAC-SHA-256 values derived from secret, scope, and
   normalized identifier/IP. Plain usernames and IPs are not used as throttle primary keys.
5. Registration atomically creates the account, client-supplied public key/fingerprint,
   KEK-wrapped AMK protection profile, encrypted private-key bundle, and audit event. A
   plaintext RSA private key and encryption passphrase never enter the API or database.
6. Password change atomically replaces the Argon2id hash, records `password_changed_at`,
   clears `must_change_password`, revokes every active session family, and appends its audit
   event. It does not alter the independent client-side encryption passphrase or account-key
   envelopes.
7. An `email_verification_codes` row stores only an HMAC-SHA-256 digest keyed by secret,
   purpose, and address, never the emailed code. Issuing a code invalidates the account's
   other pending codes for the same purpose. A row is `CONSUMED` exactly once, and
   `consumed_at` is non-null if and only if the status is `CONSUMED`.
8. A rejected code attempt is committed on its own before the caller's transaction rolls
   back. Without that, the per-code attempt counter and the verification throttle buckets
   would vanish with the rollback and leave a live code open to unlimited guessing.
9. Password reset atomically replaces the Argon2id hash, records `password_changed_at`,
   clears `must_change_password`, revokes every session family, burns the challenge, and
   appends its audit event. Like
   password change, it leaves the key-protection profile and encrypted private-key bundle
   untouched, so the account keeps access to its encrypted files.
10. Creating a file atomically creates its metadata, owner grant, owner key wrapping,
    mandatory active recovery-key wrapping, and upload audit event. The stored object is
    already client-encrypted ciphertext.
11. Download requires both an active grant with download capability and an active user key
    wrapping for the same file and actor.
12. A `USER` key wrapping has `recipient_user_id` and `user_key_id`, but no
    `recovery_key_id`. A `RECOVERY` wrapping has only `recovery_key_id`.
13. Revocation changes the logical grant and all applicable key wrappings in one transaction.
14. Recovery transitions are conditional:
    `PENDING -> APPROVED|REJECTED|CANCELLED`, then
    `APPROVED -> EXECUTED|CANCELLED`. Execution is idempotent only for the identical result
   wrapping. A requester cannot approve or reject their own request. Recovery stores an
   offline-produced target-key wrapping and never receives a recovery private key.
15. Audit rows are append-only. Appending locks singleton `audit_chain_heads.id = 1` so
    concurrent transactions cannot create two entries with the same predecessor; the audit
    append commits or rolls back with its security-sensitive use case. Actor/target user
    foreign keys are restrictive because those IDs are hashed; referenced accounts use
    status-based soft deletion rather than a cascading hard delete.
16. Each CLIENT_WRAPPED user key has an owner-consistent encrypted private-key bundle, and
    each user protection profile has a unique public UUID and optimistic revision. Rewrapping
    the AMK requires both the caller's expected revision and an RSA-PSS-SHA256 signature by
    the newest current client private key over the actor/current-key/profile/revision and
    complete proposed protection envelope; update and audit append are atomic.
17. Soft-deleted files are excluded from normal queries and cannot receive new grants.
18. A passphrase reset (`POST /keys/me/reset-protection`) replaces the protection profile and the
    encrypted private-key bundle together, keeping their public ids, under both expected
    revisions and an RSA-PSS-SHA256 signature by the account private key with its own domain
    label. The user key pair and every file wrapping are unchanged. It is refused for accounts
    with more than one current key.
19. An administrator login-password reset stores only the hash of a random temporary password,
    revokes every session of that account, and audits `ADMIN_PASSWORD_RESET` without the
    password. It refuses the caller's own account and other administrators, and never touches
    files, keys or the encryption passphrase.
20. A folder belongs to one user. An owner's placement is `files.folder_id`; a recipient's is
    `file_access_grants.folder_id`. Deleting a folder sets both to `NULL`; no file is deleted.

The service layer owns these transactions. Repositories may query, add, and `flush`; they
must not independently commit.

## Time and Identifier Conventions

- API timestamps are timezone-aware UTC ISO-8601 values.
- MySQL `DATETIME` values are written/read as UTC; conversion happens at the API boundary.
- Public URLs use UUIDs/opaque identifiers, including account and session resources.
  Auto-increment IDs remain internal database keys.
- Storage object keys, raw session credentials, token hashes, plaintext private keys, AMKs,
  KEKs, plaintext DEKs, passphrases, throttle HMACs, and filesystem roots must never appear
  in logs or public API schemas. Ciphertext, encrypted private-key bundles, and recipient-
  specific wrapped DEKs are intentionally returned only by their authorized contracts.

## Integration Test Database

The models use MySQL-specific `UNSIGNED`, `ENUM`, `VARBINARY`, JSON, collation, and referential
actions. Schema and repository integration tests therefore run against MySQL 8.4. SQLite is
not an acceptable behavioral substitute.

The minimum development migration test starts with an empty database, applies the ordered
revisions through `alembic upgrade head`, checks the current revision and expected tables,
and runs `alembic check` to detect metadata drift. A separate MySQL 8.4 production-path test
must run `01-provision.sql -> 02-schema.sql -> 03-verify.sql` against a disposable server,
inspect every verification result, and prove that the resulting schema matches the Alembic
head and ORM metadata. That test also checks the exact table-level grant matrix, absence of
the retired migrator identity and all elevated grant paths, the compatibility marker, and the
initial audit-chain singleton. Offline Alembic SQL remains a development/CI review aid, not a
production execution artifact. A legacy adoption test must begin from an explicit legacy
fixture rather than pretending it is revision `0001_initial`.
