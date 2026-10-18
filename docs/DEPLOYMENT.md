# MySQL Deployment

[English](DEPLOYMENT.md) | [Simplified Chinese](DEPLOYMENT.zh-CN.md)

These instructions target Oracle MySQL 8.4 and a new, empty application database. Production
database delivery consists entirely of three reviewed SQL files under `database/mysql/`.
A MySQL root/administrator executes them in fail-fast batch mode, in this order:

```text
01-provision.sql -> 02-schema.sql -> 03-verify.sql -> start as fyp_user
```

Production does not install or run Python/Alembic on the database server. SQLAlchemy metadata
and Alembic remain development/CI schema-authoring tools; `02-schema.sql` is the reviewed
empty-database production artifact derived from them.

## Identities and configuration

The release uses two identities:

- A MySQL root/administrator runs all three SQL files. Do not put this credential in the
  application `.env`, a command argument, or a release log.
- `fyp_user` runs the application only after verification. Inject its generated password
  through the standard application `DB_USER` and `DB_PASSWORD` settings.

The application connection also uses the existing settings:

- `DB_HOST`, `DB_PORT`, and `DB_NAME` (`fyp_secure_file_platform` for the supplied SQL)
- `DB_SSL_CA`, a readable CA bundle that verifies the server certificate and `DB_HOST`
- optionally, `DB_SSL_CERT` and `DB_SSL_KEY` together when mutual TLS is required

Verified TLS is mandatory outside development/test. Store database passwords and CA/client
files in the deployment secret store, not in Git or shell history. The normal production
settings also apply: set an appropriate `APP_ENV`, use `APP_DEBUG=false`, provide a
non-default `SECRET_KEY` of at least 32 characters, and configure explicit CORS origins.

`APP_DOCS_ENABLED` is an explicit deployment choice. It remains `true` for local development.
The SecureView public staging host also sets it to `true` because the live Swagger UI is a
team and supervisor evaluation deliverable. Requests made from Swagger receive no special
privilege: HTTPS, nginx request limits, application authentication, authorization, and audit
controls remain in force. A production deployment that does not need public API evaluation
should set it to `false`, which unmounts `/docs`, `/redoc`, and `/openapi.json` and makes them
return 404.

No deployment-only administrator, migration, or account-host environment variables are used
or should be reintroduced. `MYSQL_ROOT_PASSWORD` and `MYSQL_PORT` in `.env.example` are
local-Compose settings only; production administrator credentials never enter the application
environment.

### Storage directories

The three storage paths default to directories inside the checkout. On staging the working
directory is an immutable release under `/opt/mcs21/releases/<sha>`, which `fypapp` cannot write
and which is replaced by every deploy, so `backend.env` must point all three at the persistent
data root owned by `fypapp`:

```bash
ENCRYPTED_FILE_DIR=/var/lib/fyp-secure-file-platform/encrypted
TEMP_FILE_DIR=/var/lib/fyp-secure-file-platform/tmp
AVATAR_DIR=/var/lib/fyp-secure-file-platform/avatars
```

The application creates `avatars/` on the first upload. `AVATAR_DIR` holds plaintext profile
pictures and must never share a directory with ciphertext objects. `mcs21-deploy` already
includes the whole data root in its pre-deploy archive.

### Synchronize environment-backed request limits

`.env.example` is a versioned template; the staging service does not read it. The running
backend reads `/etc/fyp-secure-file-platform/backend.env`, while nginx enforces its own request
body ceiling before FastAPI sees a byte. A change to the advertised upload limit is therefore
complete only when all four boundaries agree:

- `frontend/src/crypto/upload.ts` for the browser-side pre-check;
- `backend/app/core/config.py` and `.env.example` for the application default and template;
- `/etc/fyp-secure-file-platform/backend.env` for the deployed application override; and
- the active nginx `client_max_body_size` directive.

For the current 500 MiB limit, staging must set
`MAX_UPLOAD_SIZE_BYTES=524288000`; nginx uses `client_max_body_size 501m` so the ciphertext plus
the bounded multipart metadata overhead can pass. Do not replace the protected environment file
with `.env.example`: it contains local-development placeholders and omits deployment secrets.
Update only the reviewed keys, preserve a timestamped backup, then validate and restart/reload:

```bash
sudo nginx -t
sudo systemctl restart fyp-backend
sudo systemctl reload nginx
curl --fail http://127.0.0.1:8000/health/ready
curl --fail https://secureview.tech/health/live
```

Confirm the value in the restarted process rather than treating the file edit as proof. A `413`
or nginx `client intended to send too large body` entry means the edge limit is still stale; an
application `file_too_large` response means the request passed nginx but the backend limit is
still stale. File media type is independent of both size checks: unknown types are stored as
`application/octet-stream`.

### Per-address limits and the venue network

nginx, fail2ban and the backend all have limits keyed on the client address. On a venue or campus
Wi-Fi every visitor arrives as the same address, so those limits were resized on 2026-10-09 for a
room of about a hundred people (the table is in [THREAT_MODEL.md §11.6](THREAT_MODEL.md)). None of
these three files is installed by `mcs21-deploy` or the CI promote: the tracked copies under
`deployment/server/` are installed by hand, so a change to them is complete only once the files on
the VPS match and the services have reloaded.

```bash
cd /opt/mcs21/current
sudo install -m 0644 deployment/server/nginx-secureview-limits.conf /etc/nginx/conf.d/secureview-limits.conf
sudo install -m 0644 deployment/server/nginx-secureview.conf /etc/nginx/sites-available/fyp-secure-file-platform
sudo nginx -t && sudo systemctl reload nginx
sudo install -m 0644 deployment/server/fail2ban/filter-secureview-auth.conf /etc/fail2ban/filter.d/secureview-auth.conf
sudo install -m 0644 deployment/server/fail2ban/jail-secureview.conf /etc/fail2ban/jail.d/secureview.conf
sudo fail2ban-client -t && sudo systemctl reload fail2ban
sudo fail2ban-client status secureview-auth
```

Diff the live nginx file against the tracked copy before installing it: certbot writes the
certificate lines, and a renewal may have touched the port-80 block. The last command lists any
address fail2ban currently bans; on the day of a presentation it should be empty, and
`sudo fail2ban-client set secureview-auth unbanip <address>` lifts one that is not.

The backend's own per-address thresholds are defaults in `backend/app/core/config.py` and apply
after the release deploys, unless `/etc/fyp-secure-file-platform/backend.env` overrides them.
Check that it does not pin the old values:

```bash
sudo grep -E 'IP_MAX|MAX_ATTEMPTS|PER_WINDOW' /etc/fyp-secure-file-platform/backend.env
```

Any line it prints wins over the code default; remove it or raise it to the current value, then
`sudo systemctl restart fyp-backend`.

## Account-host scope

The tracked files deliberately use `fyp_user@localhost`. This safe default is directly usable
when the application connects from the database host. In a MySQL account, `localhost`
describes the client source; it is not the value of `DB_HOST`.

For a remote application connection, make protected deployment copies of all three SQL files
outside the repository. Replace every `localhost` account-host literal consistently in each
copy: the `CREATE USER` target in `01-provision.sql`, every table-level `GRANT` target in
`02-schema.sql`, and every expected account/grant value in `03-verify.sql`. Use the narrowest
host name or network pattern allowed by the deployment. Do not commit the environment-specific
copies, and do not use `%` unless an independently restricted private network and firewall
make that exposure acceptable. Verification must show exactly one intended runtime host row;
an old row at another host is a distinct MySQL identity and is a deployment failure.

## 1. Provision the database and runtime account

From the repository root, connect with an administrator that can create databases, users,
and grants. The final verification also needs permission to inspect MySQL grant metadata.
On the database server, run the file directly as a socket-authenticated root account:

```bash
sudo mysql < database/mysql/01-provision.sql
```

If MySQL root uses password authentication instead, keep the password out of the command;
the client prompts for it:

```bash
mysql --user=root --password < database/mysql/01-provision.sql
```

Do not add the mysql client's `--force` option. A SQL error must stop the batch instead of
continuing through partially satisfied deployment checks.

For a remote administrator connection, use the protected environment-specific copy, supply
the administrator password interactively, and verify TLS:

```bash
mysql --host=<mysql-host> --port=3306 --user=<administrator> --password \
  --ssl-mode=VERIFY_IDENTITY --ssl-ca=/path/to/mysql-ca.pem \
  < /protected/path/01-provision.sql
```

The SQL creates `fyp_secure_file_platform` with `utf8mb4` and
`utf8mb4_unicode_ci`. It creates only `fyp_user`, requires SSL, asks MySQL to generate its
random password, and returns that cleartext password in the result set. Capture it immediately
into the secret store through a terminal/session that is not logged; it cannot be recovered
from MySQL later. Do not paste it into this repository, tickets, chat, or deployment logs.

`01-provision.sql` deliberately creates no application table and grants no table access.
`02-schema.sql` installs the exact runtime grants only after every application table exists.

The provisioning SQL is intentionally non-destructive:

- `CREATE USER IF NOT EXISTS` does not rotate an existing account's password. Retain the
  existing secret or perform a separately reviewed credential rotation.
- The later `GRANT` statements are additive. They do not revoke excess privileges or remove
  stale account-host rows.
- Existing matching accounts are not altered, including their password, authentication
  plugin, and TLS policy. Verification must show a nonempty TLS requirement; correct a
  missing requirement with a separately reviewed `ALTER USER` operation.

Review every warning and the verification output. If `fyp_user` already exists, confirm its
credential ownership, authentication plugin, nonempty password, TLS policy, host, and grants
before continuing. Correct unexpected state through a separately reviewed administrator
operation; never assume `CREATE USER IF NOT EXISTS` repaired it.

### Retire the former migrator identity

Production no longer uses `fyp_migrator`. On a server that previously used it:

1. Stop every old release job and remove the migrator credential from secret stores and job
   configuration.
2. Inventory every exact `fyp_migrator@host` account and confirm that no other owned workload
   depends on it.
3. Revoke/drop each confirmed obsolete account with a separately reviewed administrator
   change. Do not issue a wildcard or guessed `DROP USER` command.
4. Run `03-verify.sql`; any remaining account row, direct grant, role edge, default role, or
   proxy relationship for that name blocks deployment.

## 2. Install the empty-database schema

Run `02-schema.sql` as the same administrator, immediately after successful provisioning:

```bash
sudo mysql < database/mysql/02-schema.sql
# Or, when root uses password authentication:
mysql --user=root --password < database/mysql/02-schema.sql
```

For a remote administrator connection, use the matching protected copy and verified TLS:

```bash
mysql --host=<mysql-host> --port=3306 --user=<administrator> --password \
  --ssl-mode=VERIFY_IDENTITY --ssl-ca=/path/to/mysql-ca.pem \
  < /protected/path/02-schema.sql
```

Never use the mysql client's `--force` option or an interactive `SOURCE` command. The file
checks MySQL 8.4, strict SQL mode, exact database encoding, and an empty persistent schema
before permanent DDL. It is deliberately non-idempotent and must run exactly once on a clean
database. It creates all 17 application tables, the `alembic_version` compatibility marker,
the audit-chain singleton, indexes, constraints, and these exact runtime grants:

- `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on the fifteen ordinary state tables:
  `auth_login_throttles`, `recovery_keys`, `users`, `file_folders`, `files`, `user_keys`,
  `user_sessions`, `user_key_protection_profiles`, `encrypted_private_key_bundles`,
  `file_access_grants`, `file_key_wrappings`, `integrity_checks`, `recovery_requests`,
  `session_refresh_tokens`, and `email_verification_codes`;
- `SELECT` and `INSERT` only on `audit_logs`;
- table-level `SELECT` on `audit_chain_heads`, plus column-level `UPDATE` only on
  `last_log_id`, `current_hash`, and `updated_at`; and
- no runtime access to `alembic_version`, no schema/global/DDL privilege, no `GRANT OPTION`,
  and no other table/column privilege, role, proxy, or routine grant. In particular,
  `fyp_user` cannot update `audit_chain_heads.schema_revision`.

The chain-head column default and initial row both start on `0002_auth_identity_sessions`.
After the runtime grants and `alembic_version` marker succeed, the script restores the column
default to the final schema value and then explicitly publishes `0011_must_change_password` to
the singleton in the final statement. Thus readiness cannot
advertise the new schema for a partially executed install, while the completed schema remains
equivalent to the ORM and Alembic head.

MySQL DDL is not fully transactional. If any statement fails, keep the application stopped
and do not rerun the file over the partial schema. Preserve evidence, diagnose the failure,
then recreate the disposable empty database or restore the verified pre-deployment backup
before restarting at `01-provision.sql`.

The former Python runner supplied connectivity retries, advisory locking, bounded waits,
backup confirmation, and failure wrapping. The SQL does not replace release orchestration:
use a single serialized release, an overall deadline, bounded connection/metadata-lock waits,
and a tested recovery procedure.

## 3. Verify as the administrator

Run the read-only verification after `02-schema.sql` completes and before the application
starts:

```bash
sudo mysql < database/mysql/03-verify.sql
# Or, when root uses password authentication:
mysql --user=root --password < database/mysql/03-verify.sql
```

For a remote deployment, use the matching protected verification copy and the same verified
TLS connection settings:

```bash
mysql --host=<mysql-host> --port=3306 --user=<administrator> --password \
  --ssl-mode=VERIFY_IDENTITY --ssl-ca=/path/to/mysql-ca.pem \
  < /protected/path/03-verify.sql
```

Review every result set. Expected results are:

- the server is MySQL 8.4, strict SQL mode is enabled, the session time zone is the intended
  deployment value, and the application database uses `utf8mb4` with
  `utf8mb4_unicode_ci`;
- there is exactly one `fyp_user` row at the intended host, using
  `caching_sha2_password` with a nonempty hash, a nonempty SSL requirement, and no
  lock/expiry; `fyp_migrator` is absent at every host;
- neither name has a static or dynamic global privilege, schema privilege, unexpected
  table/column or routine grant, role/default-role edge, or proxy relationship, and server
  mandatory roles are empty;
- the table-grant symmetric difference is empty: exactly the fifteen-table CRUD matrix plus
  audit-log `SELECT`/`INSERT` and chain-head table-level `SELECT`, all non-grantable;
- the column-grant symmetric difference is empty: exactly non-grantable `UPDATE` on
  `audit_chain_heads.last_log_id`, `current_hash`, and `updated_at`, never
  `schema_revision`;
- the persistent table inventory, structural totals, critical foreign-key actions, check
  clauses, and composite indexes match `02-schema.sql`;
- `alembic_version` contains exactly the SQL artifact's compatibility marker
  `0011_must_change_password`; and
- `audit_chain_heads` contains exactly the genesis singleton: `id = 1`,
  `last_log_id IS NULL`, a 64-zero current hash, and
  `schema_revision = '0011_must_change_password'`.

Because account creation and grants are additive, any extra row or privilege is a deployment
failure even if the expected grants are also present. Every query in `03-verify.sql` is a
`SELECT`; it diagnoses but does not repair state. Do not start the application until excess
access or schema drift has been corrected through a reviewed operation and verification has
been rerun successfully.

## 4. Start the application

Inject `fyp_user` and its captured password through `DB_USER` and `DB_PASSWORD`, retain the
normal host/name/TLS settings, and start the application only after verification succeeds.
Do not make the administrator credential available to the application process. No migrator
credential should exist in the release or application environment.

After startup, require both `GET /health/live` and `GET /health/ready` to succeed before
adding the instance to service. Readiness executes a database probe and requires the exact
configured schema revision `0011_must_change_password`; it diagnoses drift but never migrates
or stamps the database.

## 5. Terminate TLS at nginx

The staging VPS serves `secureview.tech` over HTTPS with a Let's Encrypt certificate. The
tracked copy of the live server block is `deployment/server/nginx-secureview.conf`.

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d secureview.tech -d www.secureview.tech --redirect
```

`certbot --nginx` rewrites the port-80 block, so re-apply the loopback probe exception below
after any renewal that touches the configuration, and diff against the tracked copy.

HTTPS is not cosmetic here. The browser exposes `crypto.subtle` only in a secure context, and
registration depends on it to generate the account RSA key pair and derive the Argon2id KEK.
Over plain HTTP the API is unreachable to the client-side enrolment code, so registration
cannot complete at all.

### The port-80 block and the release probes

`mcs21-deploy` probes `http://127.0.0.1/health/live` and `http://127.0.0.1/` with a
`Host: <public_host>` header, where `public_host` is the bare server IP. Certbot's generated
redirects match only the two domain names and answer `404` for anything else, which fails the
post-deploy live health check and rolls the release back.

The port-80 block therefore keeps exactly those two paths reachable, restricted to loopback:

```nginx
location = /health/live {
    allow 127.0.0.1;
    allow ::1;
    deny all;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/proxy_params;
}

location = / {
    allow 127.0.0.1;
    allow ::1;
    deny all;
    error_page 403 = @canonical;
    try_files /index.html =404;
}

location @canonical {
    return 308 https://secureview.tech$request_uri;
}

location / {
    return 308 https://secureview.tech$request_uri;
}
```

Loopback keeps its `200` for both probes. Everyone else on port 80 is redirected to the
canonical HTTPS origin, including on the bare IP, where `error_page` turns the access-phase
`403` into that same redirect. Nothing is served over cleartext either way.

The redirect is `308`, not `301`, so that a `POST` to `/api/` keeps its method and body
instead of arriving as a `GET` and failing with `405`.

### Reaching the box by IP

The 443 block lists the bare IP in `server_name`, so `https://<server-ip>/` does reach the
site — but the Let's Encrypt certificate covers only `secureview.tech` and
`www.secureview.tech`, so a browser shows a name-mismatch warning. Let's Encrypt does not
issue for IP addresses, and an IP has no name to validate.

Use `https://secureview.tech`. `http://<server-ip>/<path>` redirects there, which is the
supported way in: the API docs, for instance, are reachable by typing the IP and landing on
`https://secureview.tech/docs`.

For presentations and supervisor review, use the canonical Swagger URL directly:
`https://secureview.tech/docs`. Do not share an HTTPS URL containing the bare IP: the TLS
certificate proves the domain name, not the address.

Before this redirect existed, the bare IP over HTTP answered `404` from nginx for every path
but the two loopback probes. That page is easy to read as a dead backend when it is really
just cleartext being refused a name it can redirect to.

### First-visit HTTP hop

`.tech` is not on the browser HSTS preload list, so a visitor who types `secureview.tech`
without a scheme reaches `http://` once before the redirect. The `Strict-Transport-Security`
header then pins HTTPS for a year. Publish and share the URL as `https://secureview.tech` so
that first hop never happens; some in-app browsers warn on it.

## When the dependency install stalls

`mcs21-deploy` builds every release in a fresh `.build-*` directory with its own virtual
environment, so each deploy downloads the backend requirements. On 2026-10-05 one pip
connection trickled at about 29 kB/s on a 4.7 MB wheel that the same host fetched in under a
second, and the deploy sat there for over seven minutes; pip's own `--timeout` never fired
because bytes kept arriving.

Each `pip install` attempt now has a wall-clock limit (`MCS21_PIP_ATTEMPT_SECONDS`, default
240) on top of pip's `--timeout 30 --retries 5`, and a stalled or failed attempt is started
again up to `MCS21_PIP_ATTEMPTS` times (default 3, `MCS21_PIP_RETRY_PAUSE` seconds apart,
default 10). A normal install takes under a minute. Only when every attempt fails does the
deploy fail, and it then removes its `.build-*` directory instead of leaving it behind.
`backend/tests/unit/test_ops_units.py` runs the real function against a fake pip that hangs
once.

`mcs21-deploy` itself lives in `/usr/local/sbin` and is installed by hand: after this file
changes, copy it from the new release
(`install -m 0755 /opt/mcs21/current/deployment/server/mcs21-deploy /usr/local/sbin/`).

## Applying a schema revision to a running deployment

`mcs21-deploy` never changes the schema. It backs the database up and runs `03-verify.sql`
read-only; its own help text says so, and the automatic deployment identity holds no MySQL
administrator credential. A release that carries a new Alembic revision therefore has a
manual step, and getting its **order** wrong takes the site down or quarantines the release.

### Why the order is forced

`GET /health/ready` compares `audit_chain_heads.schema_revision` against the running code's
`EXPECTED_SCHEMA_REVISION` and requires them to be **exactly equal** — not "at least". So
there is no ordering in which both halves are correct at once, and a window of `503
schema_incompatible` is unavoidable. What differs is how the two orderings fail:

- **Code first.** `verify_database()` greps the verification log for `REVIEW`, `MISSING` or
  `UNEXPECTED` and calls `die` on a match, so the deploy aborts. The post-deploy health check
  then fails, the release rolls back, and the SHA is quarantined — and
  `mcs21-auto-deploy` does not retry a quarantined SHA, so every later commit is blocked
  behind it too.
- **Database first.** The running code briefly answers `503` while it expects the previous
  revision. The next automatic deploy, two minutes later at most, brings the code forward and
  the window closes on its own.

**Change the database first.** The failure mode is a short outage rather than a stuck
pipeline.

Note also that a revision string appears in roughly thirty places — `config.py`,
`audit_chain_head.py`, `02-schema.sql`, `03-verify.sql`, and several test files. Updating only
some of them is what quarantined an earlier release; `tests/unit/test_migration_metadata.py`
and `tests/unit/test_mysql_sql_deployment.py` exist to catch a half-finished rename, so run
the backend unit suite before starting any of this.

### Deriving the SQL

Do not hand-write the statements. Render them from the revision itself, so what runs on the
server is what the migration says:

```bash
cd backend
.venv/bin/alembic upgrade <previous_revision>:<new_revision> --sql
```

Guard queries inside a migration cannot run in this mode — there is no connection to ask — so
they are skipped, and the rendered script relies on the constraints themselves. Read the
output before running it, and reproduce any guard as an explicit pre-check in step 2.

### Procedure

1. **Prepare the code but do not push.** Commit, merge to `main`, and stop before
   `git push`. The push should be a single command ready to fire, because it is what closes
   the `503` window.

2. **Back up.** `sudo mcs21-deploy database` on the server. It also runs the read-only
   verification against the *currently deployed* release, so it should pass; if it does not,
   stop and diagnose rather than layering a schema change on top of an existing problem.

3. **Pre-check, read-only.** Confirm the starting revision in both `alembic_version` and
   `audit_chain_heads`, and confirm every row the new constraints will validate already
   satisfies them. MySQL DDL commits per statement and cannot be rolled back, so a
   `DROP CHECK` that succeeds followed by an `ADD CONSTRAINT` that fails leaves the table
   with no constraint at all. The pre-check is what keeps that from happening.

4. **Apply the SQL,** ending with the two readiness markers and `alembic_version`. Raise the
   markers last: a failure part-way must never advertise a schema the database does not have.

5. **Push immediately.** The site is answering `503` from this moment until the deploy
   completes, normally two to three minutes.

6. **Confirm.** `result=success` and `health=ok` in `journalctl -u mcs21-auto-deploy`, and
   `{"status":"ready"}` from `https://secureview.tech/health/ready`.

### Rolling back

`sudo mcs21-deploy rollback` **changes the code release only and never the database**. Using
it alone after a schema change leaves old code against a new schema, which is exactly the
`503 schema_incompatible` state — so a rollback must revert both halves: the SQL, then
`git revert` on the merge commit.

Reversibility is also time-limited whenever a revision widens what a column may hold. Narrowing
it again fails once a row uses the new value, and those rows are usually intact data rather
than corruption — the guards in `0005` and `0006` refuse the downgrade for that reason rather
than deleting them. Decide quickly, or accept that going back means re-encrypting or deleting
real files.

Restoring the backup from step 2 is the last resort, not the plan. It discards everything
written since the dump — uploads, registrations, audit rows, sessions — while the ciphertext
on disk remains, leaving the two out of step.

## Legacy and failed deployments

The former `docs/init.sql` was a historical development bootstrap and has been deleted. A
database previously created from it may contain application tables but no `alembic_version`;
it remains unmanaged. Follow the
[legacy adoption policy](DATABASE_SCHEMA.md#adopting-a-legacy-development-database).
`02-schema.sql` refuses that non-empty schema. Never run production Alembic, edit/stamp the
compatibility marker, or add `IF NOT EXISTS` clauses merely to bypass the refusal.

The three-file procedure is a fresh-database bootstrap, not an upgrade strategy. A future
release against a non-empty staging/production database requires a separate immutable,
versioned DBA SQL script derived from the reviewed schema change. Before that script runs,
drain writers, serialize the release, verify the current marker/schema, take and test a
restorable encrypted backup, and set bounded connection and metadata-lock waits. The matching
verification expectations must be updated for that release.

If schema installation or a future DBA upgrade fails, keep the application stopped and
preserve the database for diagnosis. MySQL DDL can commit incrementally, so recovery normally
means recreating the disposable empty database or restoring the verified backup. Do not run
`alembic downgrade`, manually edit `alembic_version`, or rerun `02-schema.sql` over partial or
existing state.

Store backups outside this repository, encrypt them, restrict access, and test restoration.
Database dumps contain login-password hashes, public Argon2id parameters, wrapped AMKs,
client-encrypted private-key bundles, security audit evidence, plaintext operational file
metadata, and wrapped file keys. These are not plaintext private keys or DEKs, but the dump
still enables offline passphrase guessing and reveals the ownership/sharing graph; protect it
as highly sensitive data.

## Container note

The root `docker-compose.yml` is a local MySQL convenience, not a production deployment
stack. On a fresh volume the image creates `DB_NAME` and grants its configured `DB_USER`
database access; that account can be broader than the production runtime grant. Existing
volumes retain their accounts and grants, so changing `.env` does not reprovision them and
the strict production verification may correctly report excess access.

Do not source the production provisioning file into an ordinary Compose development volume
unless deliberately adopting its account policy. It does not replace or otherwise alter an
existing Compose account, and cannot revoke the broader grant that the image may already
have assigned.

Do not mount the production SQL files or Alembic revisions under
`/docker-entrypoint-initdb.d`. Image initialization runs only for a fresh volume, generated
passwords must be captured securely, and existing deployments would silently miss later
release steps. Run `01`, `02`, and `03` explicitly as administrator-controlled operations.
