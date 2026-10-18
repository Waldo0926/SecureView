# Backend

[English](README.md) | [简体中文](README.zh-CN.md)

FastAPI modular-monolith backend for the secure file encryption and sharing platform.

## Current Status

The Auth, password-wrapped key custody, encrypted-file, sharing, audit, recovery, and admin
vertical slices are implemented. They use real MySQL transactions, public UUID contracts,
explicit bearer/RBAC dependencies, encrypted object storage, and chained audit events.
The core Auth endpoints under `/api/v1` are:

| Method | Endpoint | Authentication |
|---|---|---|
| POST | `/auth/verification-codes/send` | Public |
| POST | `/auth/register` | Public |
| POST | `/auth/password-reset` | Public |
| POST | `/auth/login` | Public |
| POST | `/auth/refresh` | Refresh credential |
| GET | `/auth/me` | Bearer access token |
| POST | `/auth/logout` | Bearer access token |
| POST | `/auth/logout-all` | Bearer access token |
| POST | `/auth/delete-account` | Bearer access token + password confirmation |
| POST | `/auth/change-password` | Bearer access token |
| GET | `/auth/sessions` | Bearer access token |
| POST | `/auth/sessions/{session_id}/revoke` | Bearer access token |
| POST | `/auth/avatar/upload` | Bearer access token |
| GET | `/auth/avatar` | Bearer access token |
| POST | `/auth/avatar/delete` | Bearer access token |

The `/keys`, `/files`, `/audit-logs`, `/recovery`, and `/admin` routers are also active and
fully described by OpenAPI. `/health/live` checks the process; `/health/ready` additionally
checks database access and schema revision `0011_must_change_password`. Administrators can also
view one account's details and issue a temporary login password
(`GET /admin/users/{user_id}`, `POST /admin/users/{user_id}/reset-password`, #197); that never
touches files, keys or the encryption passphrase.

Registration requires `username`, `email`, `password`, `verification_code`, and
`key_material`. The client generates the account RSA key pair and both envelopes locally and
uploads only the public key and the sealed material, so the backend never receives an
encryption passphrase, AMK, or plaintext private key. Registration and login-password reset
are gated by a one-time code emailed to the address being claimed, which also marks the
account's email verified. Reset never touches the stored key envelopes, so it cannot cost an
account access to its encrypted files.

The encryption passphrase is independent of the login password and only ever derives the KEK in
the client. A user normally needs to remember just that passphrase, because the server keeps the
encrypted private-key bundle. The server cannot reset or recover a lost passphrase; the holder of
the private key file (`.pem`, offered once at registration) sets a new one in Settings (or, while
the passphrase is still known, Settings changes it with the current one, #201), and losing
both makes the files unrecoverable. The recovery API only governs rewrapping one file's DEK to an
already registered active public key; it does not recover the passphrase or the AMK, or decrypt
the private-key bundle.

### Server-managed account-key envelope (format 2): removed

The server-side account-key generation from the server-managed registration experiment
(`CryptoService.generate_account_key`, `decrypt_account_private_key`,
`rewrap_key_protection_profile`, kept unused since the revert to client-held custody) has been
removed. Registration takes client-generated `key_material` because
`docs/SECURITY_FLOWS.md` requires the backend never to hold a plaintext private key, so there
was nothing for that code to do. `CryptoService` keeps only what the API uses: public-key
loading and fingerprints, wrapped-key length checks, RSA-PSS signature verification, and the
AAD / HKDF-info builders below, which remain as the documented byte layout
(`tests/unit/test_crypto_service.py` pins it).

Integers are unsigned 32-bit big-endian values, UUIDs are their raw 16-byte RFC 4122/network-order
representation, and the public-key fingerprint is the raw 32-byte SHA-256 value decoded from its
hexadecimal API representation. Concatenation is shown as `||`; each domain string ends with
one `0x00` byte.

- AMK wrapping AAD: `FYP-KEY-PROTECTION || 0x00 || format_version || aad_version || profile_uuid`
- Private-key HKDF info: `FYP-PRIVATE-KEY-DERIVATION || 0x00 || format_version || profile_uuid || key_uuid || bundle_uuid`
- Private-key AAD: `FYP-PRIVATE-KEY-BUNDLE || 0x00 || format_version || aad_version || profile_uuid || key_uuid || bundle_uuid || public_key_fingerprint`

Application HTTP endpoints use only `GET` for reads and `POST` for creation, updates,
deletion, revocation, and other state-changing actions. Do not add `PUT`, `PATCH`, or
`DELETE` routes. CORS method configuration is restricted to `GET` and `POST`.

The login-password policy normalizes with Unicode NFC, requires 8 to 128 characters and at
least two of uppercase, lowercase, number, and symbol classes, rejects account-derived/common
values, and hashes with Argon2id. The separate client-only encryption passphrase has a
10-character minimum. Valid legacy bcrypt hashes are transparently upgraded; memory-hard
operations fail fast when the configured per-worker capacity is full. The included
common-password list is a small local safety baseline, not a maintained breached-password
corpus.

Registration and forgotten-login-password reset are gated by a one-time code emailed to the
address being claimed, which also marks the account's email verified. Codes are stored only
as keyed digests, expire, are single use, are attempt-bounded, and are rate limited per
address and per IP; the send endpoint answers identically for registered and unregistered
addresses. Reset never touches the account's key envelopes, so it cannot cost an account
access to its encrypted files, and it correspondingly cannot recover a forgotten encryption
passphrase. MFA and external identity login are not implemented.

## Prerequisites

- Python 3.11 or newer (CI and staging use 3.12)
- Docker with Compose (recommended for MySQL 8.4)

The canonical command directory for backend commands is `backend/`. Configuration always
loads the repository-root `.env`, and configured relative storage paths are resolved from
the repository root rather than the process working directory.

`MAX_REQUEST_BODY_BYTES` limits ordinary JSON/form request bodies (1 MiB by default, with an
8 MiB configuration ceiling). The encrypted multipart upload route uses its separate
`MAX_UPLOAD_SIZE_BYTES + MAX_UPLOAD_REQUEST_OVERHEAD_BYTES` cap, so increasing the ordinary
body limit does not change the permitted ciphertext size.

## First Setup

From the repository root, create `.env` only if it does not already exist:

For this local development setup, before running `alembic upgrade head`, confirm the target
database is clean or already has an `alembic_version` row. The currently inspected local
legacy database does not; follow
the [database adoption policy](../docs/DATABASE_SCHEMA.md#adopting-a-legacy-development-database)
instead of running or stamping the normal history against it.

```powershell
Copy-Item .env.example .env
docker compose up -d --wait mysql
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
alembic upgrade head
```

macOS/Linux activation command:

```bash
source .venv/bin/activate
```

Do not commit `.env`, private keys, recovery keys, runtime files, or encrypted test data.

Compose creates `DB_NAME` and `DB_USER` only while initializing a fresh local volume. This is
a development convenience: it does not reproduce the table-scoped least-privilege runtime
account used by the staging/production procedure.

## Run

Development:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

OpenAPI: <http://localhost:8000/docs>

Liveness: <http://localhost:8000/health/live>

`--reload` is for local development only. A deployment must use injected non-default
secrets, `APP_DEBUG=false`, explicit CORS origins, and a supervised process/container.

## Quality Checks

Run from `backend/`:

```bash
ruff format --check app tests migrations
ruff check app tests migrations
pytest
alembic check
pip-audit -r requirements.txt
```

Integration tests that exercise ORM behavior must use MySQL 8.4 because the schema uses
MySQL-specific unsigned integers, enums, binary columns, collation, JSON, and referential
actions. Do not substitute SQLite for those tests.

### Integration tests against a real database

`pytest` alone skips every test under `tests/integration/`, so a green run does not mean they
passed. Point `AUTH_TEST_DATABASE_URL` at a disposable, already-migrated database to make
them run. The name must carry a distinct `_test` segment; the fixture refuses anything else,
because these tests write and delete rows.

```bash
mysql --user=root --password -e "CREATE DATABASE fyp_secure_file_platform_test \
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
AUTH_TEST_DATABASE_URL='mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/fyp_secure_file_platform_test?charset=utf8mb4' \
  alembic upgrade head
AUTH_TEST_DATABASE_URL='mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/fyp_secure_file_platform_test?charset=utf8mb4' \
  pytest
```

`test_file_lifecycle_mysql.py` covers upload, listing, download, integrity, sharing state and
deletion against that database and a real storage root under `tmp_path`. It exists because
several defects live only where the service, the SQL, and the object store meet, and a fake
storage or a fake session cannot see them. Each run creates its own identity and removes its
own file rows afterwards; audit rows and the identity they reference are left in place on
purpose, since the audit chain is append-only and deleting from the middle of a hash chain
would destroy the property it exists to provide.

## Reconciliation

Four tables grow without bound on ordinary traffic — sessions, refresh tokens, throttle
buckets, and verification codes — and none of them is read once it lapses, because expiry
is decided from the timestamps at request time rather than from a stored flag. Storage has
the mirror problem: a process that dies between publishing a ciphertext object and
committing its row leaves an object no row names.

```bash
.venv/bin/python scripts/reconcile.py            # report only, the default
.venv/bin/python scripts/reconcile.py --apply    # actually delete
```

Reporting is the default deliberately: a reconciler is the kind of job whose bugs are
discovered by what it removed, so the first run on a deployment should be read rather than
trusted. It never touches `audit_logs` or `audit_chain_heads` (append-only, hash-chained,
and the runtime grant is `SELECT, INSERT` so this cannot happen by accident), the file
tables, the identity and key-custody tables, or `recovery_requests`.

`deployment/server/mcs21-reconcile.{service,timer}` run it daily. On staging they were installed
on 2026-09-24 after a report-only run had been read, and the timer has run daily since 2026-09-25
(#57, closed). On a new deployment, read a report-only run before enabling them.

## Database Changes

SQLAlchemy metadata and Alembic remain the schema-authoring workflow for local development
and CI. The application never calls `create_all()` and Compose no longer mounts a destructive
table-initialisation script. These commands are not run on a production database server:

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe the change"
alembic check
```

Review every autogenerated revision before committing it. CI must prove that the reviewed
production schema artifact matches the current Alembic head and ORM metadata.

For a new staging or production database, return to the repository root on the database
server. A MySQL root/administrator runs all three reviewed files in fail-fast batch mode:

```bash
sudo mysql < database/mysql/01-provision.sql
sudo mysql < database/mysql/02-schema.sql
sudo mysql < database/mysql/03-verify.sql
```

Capture the one generated `fyp_user` password in the deployment secret store. The empty-only
`02-schema.sql` installs sixteen application tables plus the `alembic_version` compatibility
table and exact runtime grants: CRUD on fourteen ordinary state tables, `SELECT`/`INSERT` on
`audit_logs`, and column-limited `UPDATE` on `audit_chain_heads` that excludes
`schema_revision`; `alembic_version` is not exposed to the application. The read-only
`03-verify.sql` must report the exact expected schema and grants and no legacy
`fyp_migrator` account. Start the application only after verification, using `fyp_user`
through the standard `DB_*` settings. Account provisioning, remote-host customization,
backup requirements, and the required release safeguards are documented in
[DEPLOYMENT.md](../docs/DEPLOYMENT.md).

`02-schema.sql` is non-idempotent and accepts only an empty schema. Never rerun it over an
existing deployment. Future non-empty production upgrades require a separate, versioned,
reviewed DBA SQL script plus a verified backup; production does not run or stamp Alembic.

If an older local development database was created by the historical, now-deleted
`docs/init.sql`, read the legacy adoption warning in `docs/DATABASE_SCHEMA.md` before using
the development Alembic workflow. The Auth migration safely follows the Alembic baseline but
does not turn an unmanaged legacy schema into a managed one.

## Architecture Rules

The concise rules and security/transaction boundaries are documented in:

- [Backend architecture](../docs/ARCHITECTURE.md)
- [Database schema policy](../docs/DATABASE_SCHEMA.md)
- [Security flows](../docs/SECURITY_FLOWS.md)
- [API design](../docs/API_DESIGN.md)

The key dependency rule is: router -> use-case service -> repository/storage/crypto policy.
Routers contain no SQL or filesystem logic; repositories never commit; one use case owns
the transaction and storage compensation behavior.
