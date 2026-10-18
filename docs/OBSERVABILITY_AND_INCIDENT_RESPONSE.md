# Observability and Incident Response Runbook

[English](OBSERVABILITY_AND_INCIDENT_RESPONSE.md) | [Simplified Chinese](OBSERVABILITY_AND_INCIDENT_RESPONSE.zh-CN.md)

This runbook is the operational contract for issue #59. It adds observability without turning
logs, metrics, or alert email into a second copy of user data. The application remains an FYP
prototype: these controls improve detection and response, but they are not a claim of external
security certification.

## 1. Data-minimising event model

The application emits compact JSON events through logger `secureview.events`. Event fields are
operational metadata only. They never intentionally include request/response bodies, query
strings, exception messages, filenames, file contents, email addresses, usernames, bearer or
refresh tokens, passwords/passphrases, wrapped keys, PEM material, cookies, or private keys.
`backend/app/core/observability.py` also redacts field names associated with those values as a
last guard.

The client address is not logged exactly. Uvicorn resolves the trusted proxy boundary first;
the event layer then reduces IPv4 to `/24` and IPv6 to `/64`. Routes are logged as FastAPI route
templates such as `/api/v1/recovery/{request_id}/approve`, never the concrete UUID-bearing URL.
A random 16-hex-character request ID correlates events within one request without using a user
identifier.

| Event | Trigger | Safe fields |
|---|---|---|
| `auth.failure` | backend authentication failure | request ID, method, route template, redacted client network, stable error code |
| `auth.rate_limited` | application throttle fires | same fields; warning level |
| `storage.unavailable` | storage layer unavailable | route template and stable error code; no object key or filename |
| `storage.integrity_failure` | integrity verification refuses a file | route template and stable error code; no file identifier/content |
| `readiness.failed` / `readiness.recovered` | DB unavailable or schema revision mismatch/recovery | readiness state and schema revision only |
| `recovery.operation` | a POST recovery operation returns | route template, status, duration and redacted client network; request body/reason/key material excluded |
| `application.unhandled_error` | unexpected exception | exception **type** only, never exception text |

Deploy and rollback outcomes already have a separate operator audit trail in
`/var/log/mcs21-deploy/audit.log` and journald. `mcs21-deploy` writes controlled fields
`caller`, `action`, `result`, commit/backup paths, or a controlled failure location; it never
logs backend environment contents or database passwords.

Database retries are logged separately on `secureview.db` (#202): one warning per retried
transaction, `mysql_transaction_retry code=1213 attempt=2 of 3`, with the MySQL error code and the
attempt number only, never the statement or its parameters.
`journalctl -u fyp-backend | grep mysql_transaction_retry` counts how often deadlocks (1213) or
lock-wait timeouts (1205) were retried.

## 2. Host-local metrics

`GET http://127.0.0.1:8000/internal/metrics` is a host-local operations surface. Production
Uvicorn binds to `127.0.0.1`; tracked nginx proxies `/api/`, health, and optional docs routes,
but does **not** proxy `/internal/`. The endpoint is omitted from OpenAPI and returns counters
only:

- process start and uptime;
- request, 4xx and 5xx totals;
- authentication failures and application rate-limit totals;
- storage and integrity-failure totals;
- unexpected-error totals;
- readiness/schema-mismatch transitions;
- recovery POST-operation totals.

Counters reset on backend restart. `backend/scripts/observe_runtime.py` records the process
start ID and therefore treats a restart as a new baseline rather than generating a false
negative or burst.

### Alert thresholds

`mcs21-observe.timer` samples every five minutes. A newly crossed threshold makes
`mcs21-observe.service` fail once, which activates `mcs21-alert@.service`. Persistent breaches
stay in every JSON metrics snapshot but do not email every five minutes; a newly added breach
alerts again.

| Signal, per five-minute interval unless stated | Threshold | Primary response owner |
|---|---:|---|
| backend readiness | anything other than `ready` | Operations/deployment owner |
| application rate-limit responses | 5 | Security owner, with operations support |
| authentication failures | 50 | Security owner |
| storage-unavailable events | 3 | Operations/deployment owner |
| integrity-refusal events | 3 | Security + operations |
| unexpected application errors | 3 | Backend owner |
| schema mismatch transition | any | Backend + operations |
| filesystem usage | 85% used | Operations/deployment owner |
| external audit checkpoint age | missing or > 2 hours | Security + operations |

These are staging thresholds, chosen to detect a material change while tolerating ordinary FYP
testing. Review them against measured traffic before any production claim; do not silently
raise a threshold merely to stop alerts.

## 3. Trusted proxy boundary

The backend must never trust `X-Forwarded-For` from arbitrary clients. The staging topology is:

```text
Internet -> nginx :443 -> Uvicorn 127.0.0.1:8000
```

The Uvicorn invocation must include both:

```text
--proxy-headers --forwarded-allow-ips=127.0.0.1
```

Only the loopback nginx peer may therefore supply proxy headers that alter `request.client`.
The application event layer consumes that already-resolved address and then reduces it to a
network prefix. Before enabling #59 on a host, verify the live unit rather than assuming the
tracked preflight command matches it:

```bash
sudo systemctl cat fyp-backend | grep -E -- '--proxy-headers|--forwarded-allow-ips'
sudo ss -ltnp | grep ':8000'
# Expect 127.0.0.1:8000 and forwarded-allow-ips=127.0.0.1.
```

If the backend ever moves behind another proxy, load balancer, container bridge, or CDN, stop
and update this trust list deliberately. Never use `--forwarded-allow-ips='*'` on an
Internet-reachable listener.

## 4. External audit-chain checkpoints

The in-database audit chain detects ordinary mutation, but a database administrator or attacker
who can rewrite both `audit_logs` and `audit_chain_heads` could manufacture a self-consistent
replacement. `backend/scripts/audit_checkpoint.py` therefore publishes the current chain head
to storage outside the application database.

A checkpoint contains only:

- format version and UTC creation time;
- exact deployed Git commit;
- `last_log_id`, `current_hash`, `schema_revision`, and the chain-head update time;
- HMAC-SHA256 over the canonical payload.

It contains no audit rows or user/file content. The HMAC key is a separate root-only 256-bit
random value and is never passed to the backend process. Staging should put checkpoints under a
dedicated prefix of the existing object-locked Cloudflare R2 backup bucket. Existing immutable
older checkpoints are the independent trust anchor: a later host compromise cannot rewrite
their authenticated payloads inside the retention/lock window.

### Key and destination setup

Keep an offline copy of the HMAC key for independent verification. On the VPS:

```bash
sudo install -d -o root -g root -m 0700 /etc/fyp-secure-file-platform
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/fyp-secure-file-platform/audit-checkpoint.key'
sudo chmod 0400 /etc/fyp-secure-file-platform/audit-checkpoint.key

# Reuse only the existing read-only backup DB account and S3-compatible put credential.
# audit-checkpoint.env itself contains the external prefix, not an HMAC secret.
sudo sh -c 'cat > /etc/fyp-secure-file-platform/audit-checkpoint.env <<EOF
AUDIT_CHECKPOINT_DEST=s3://<bucket>/<prefix>/audit-checkpoints
EOF'
sudo chmod 0600 /etc/fyp-secure-file-platform/audit-checkpoint.env

sudo install -d -o fypapp -g fypapp -m 0750 /var/lib/mcs21-observe
```

`mcs21-audit-checkpoint.service` reads `backup.env` for the already least-privilege backup DB
and S3 settings, plus `audit-checkpoint.env` for the dedicated destination. It deliberately
does not read `backend.env`. The service runs as root only so the application account cannot
read the HMAC key; systemd hardening keeps the rest of the filesystem read-only.

### Install and exercise once

```bash
R=/opt/mcs21/current
sudo install -o root -g root -m 0644 \
  "$R/deployment/server/mcs21-audit-checkpoint.service" \
  "$R/deployment/server/mcs21-audit-checkpoint.timer" \
  "$R/deployment/server/mcs21-observe.service" \
  "$R/deployment/server/mcs21-observe.timer" \
  /etc/systemd/system/
sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-alert" /usr/local/sbin/mcs21-alert
sudo systemctl daemon-reload
sudo systemd-analyze verify \
  /etc/systemd/system/mcs21-audit-checkpoint.service \
  /etc/systemd/system/mcs21-audit-checkpoint.timer \
  /etc/systemd/system/mcs21-observe.service \
  /etc/systemd/system/mcs21-observe.timer

sudo systemctl start mcs21-audit-checkpoint.service
sudo journalctl -u mcs21-audit-checkpoint.service -n 20 --no-pager
sudo cat /var/lib/mcs21-observe/audit-checkpoint.latest

sudo systemctl start mcs21-observe.service
sudo journalctl -u mcs21-observe.service -n 20 --no-pager

sudo systemctl enable --now mcs21-audit-checkpoint.timer mcs21-observe.timer
systemctl list-timers mcs21-audit-checkpoint.timer mcs21-observe.timer
```

The first observer run establishes a counter baseline. It must report `health_status=ready`,
disk below threshold, and a fresh checkpoint.

### Independent verification

Download one checkpoint on a separate trusted machine and copy the HMAC key through a separate
operator-controlled channel. Do not put the key in Git, chat, CI artifacts, or the R2 bucket.
From a checkout of the same code:

```bash
cd backend
python scripts/audit_checkpoint.py verify /path/to/audit-checkpoint-....json \
  --key-file /offline/path/audit-checkpoint.key
```

For an incident comparison against a database copy or the live read-only backup connection:

```bash
# Set CHECKPOINT_DB_* or BACKUP_DB_* to a read-only account first.
python scripts/audit_checkpoint.py verify-live /path/to/audit-checkpoint-....json \
  --key-file /offline/path/audit-checkpoint.key
```

`verify-live` checks that the audit row at the checkpoint's `last_log_id` still has exactly the
externally authenticated hash and that the live chain has not moved backwards. This catches a
self-consistent database rewrite that no longer contains the old anchor.

## 5. Alert transport is intentionally sparse

`mcs21-alert` no longer emails raw journal lines. Journals are useful locally, but sending them
through a third-party mail provider would make every future logging regression a possible data
leak. Alert mail contains only the unit, host, time, systemd result/exit status, this runbook,
and the exact local `journalctl` command.

The Resend API key is still provided to `curl` through a mode-0600 header file and is never put
on argv or printed. The response body is not logged because it can echo recipient addresses.

## 6. Incident procedures

### A. Backend/site outage

1. `systemctl status fyp-backend nginx --no-pager`.
2. `curl -i http://127.0.0.1:8000/health/live` and `/health/ready`.
3. `journalctl -u fyp-backend -n 100 --no-pager`; look for structured readiness/unhandled-error events.
4. If a new deployment preceded the outage, run `sudo mcs21-deploy status` and inspect
   `/var/log/mcs21-deploy/audit.log`.
5. Roll back code only when the schema is unchanged. For a schema change, follow
   `docs/DEPLOYMENT.md`; code-only rollback can itself create `schema_incompatible`.
6. Preserve journals and deployment audit records before restarting repeatedly.

### B. Ciphertext storage corruption or integrity alerts

1. Do **not** delete or overwrite the object. Record the time and affected public file UUID from
   the authenticated UI/API investigation, not in a public issue.
2. Stop any manual cleanup: `sudo systemctl stop mcs21-reconcile.service` and, if necessary,
   `sudo systemctl disable --now mcs21-reconcile.timer`.
3. Run the app integrity check and compare `files.encrypted_sha256` with the object SHA-256.
4. Review the most recent same-host/off-server backup and the tamper-drill runbook. Restore only
   the specific verified ciphertext object; never restore the whole live database just to fix
   one object.
5. If database and object hashes agree but client AEAD authentication fails, treat it as a
   database+storage compromise until disproven.

### C. Suspected credential/token compromise

1. Identify the credential class: user session, runtime DB account, backup account, Resend key,
   S3/R2 key, or operator SSH credential.
2. Revoke/rotate that credential at its authority first; do not merely edit a local file while
   the old value remains valid.
3. For user sessions, revoke the server-side session family. For infrastructure credentials,
   replace the root-only env file and restart only the unit that consumes it.
4. Search local structured logs for the relevant **event types and time window**, not for the
   secret value itself. Secrets should never be searchable because they should never have been
   logged.
5. If any secret appears in a log, email, CI artifact, or Git history, treat the sink as
   compromised, rotate the credential, preserve evidence, and open an incident issue without
   pasting the value.

### D. Failed migration or schema mismatch

1. Stop automatic deploy attempts for the target SHA.
2. Capture `/health/ready`, `alembic current`, `alembic heads`, and the deployment audit entry.
3. Follow the reviewed forward/rollback SQL procedure in `docs/DEPLOYMENT.md`; do not stamp a
   mismatched database to silence the readiness check.
4. Re-run tracked `database/mysql/03-verify.sql` and the normal health probes before clearing the
   incident.

### E. Audit-chain failure or external checkpoint mismatch

1. Freeze destructive admin/recovery work and preserve the database plus external checkpoints.
2. Verify at least one older external checkpoint offline with `audit_checkpoint.py verify`.
3. Run the existing audit-chain verifier, then `verify-live` against the externally authenticated
   checkpoint.
4. A valid internal chain that fails the external anchor is evidence of a rewritten chain; do
   not "repair" it in place. Preserve the DB, checkpoints, deployment logs and backups for
   review.
5. Rotate the checkpoint HMAC key only if its custody is suspect. Rotation does not invalidate
   already retained checkpoints; retain the old key offline for their verification window.

### F. Recovery-key incident

1. Disable or revoke the affected recovery public key through the authorized workflow; do not
   upload private recovery material to the server.
2. Pause recovery executions while custody is investigated.
3. Review `recovery.operation` structured events and the tamper-evident audit records. The
   observability stream intentionally lacks reasons, wrapped keys and PEM material.
4. If rotating the recovery public key, follow the requester/reviewer separation and confirm
   which file recovery wrappings need successor handling before revoking the previous key.
5. Record the finding and disposition without publishing recovery private keys or execution
   packages.

## 7. Verification that sensitive data stays out

CI/unit tests must continue to prove all of the following:

- observability redacts token/password/passphrase/private-key/filename/content fields;
- recovery events contain route templates rather than concrete request IDs;
- alert email does not contain journal output;
- the alert API key never appears in `curl` argv;
- the audit checkpoint document contains only anchor metadata;
- the checkpoint HMAC key is not in `backend.env` and the checkpoint service does not expose it
  to the application process;
- the metrics state file contains counters and breach codes only.

A real staging validation should additionally use synthetic marker strings in a throwaway test
request, then confirm those markers are absent from `journalctl`, alert email, the metrics state
file, and the external checkpoint. Never use a real password, token, private key, or user file
as the marker.

## 8. Staging evidence record

These rows were filled from the host result recorded in Issue #59 (2026-09-25), which closed the Issue; where staging was observed again on 2026-10-01 that is noted.

| Item | Evidence |
|---|---|
| Exact merged/deployed SHA | `0beb967949442a72b9553e7842d82041e39ff27b`, healthy on staging, 2026-09-25 (staging has since moved on; it ran `70fcb6d` on 2026-10-01) |
| Live Uvicorn bind + trusted proxy args verified | Backend listens on loopback only and trusts forwarded headers only from `127.0.0.1`, 2026-09-25; 127.0.0.1:8000 and 127.0.0.1:3306 re-observed on 2026-10-01 |
| `/internal/metrics` reachable on loopback and not exposed by nginx | Works locally; nginx answers 404 for the same path over HTTPS, 2026-09-25 |
| First external checkpoint uploaded and stamp fresh | Published to R2 on 2026-09-25; the timer was still publishing hourly on 2026-10-01 (`audit-checkpoint-20261001T011600Z-602.json`) |
| Checkpoint independently verified off-host | Downloaded with a matching SHA-256 and HMAC-verified on a separate Mac, 2026-09-25 |
| `mcs21-observe` baseline healthy and timers enabled | Baseline `health_status=ready`, no active breaches, fresh checkpoint, normal disk; both timers enabled and active, 2026-09-25; no active breaches on 2026-10-01 |
| Synthetic redaction markers absent from local/alert/checkpoint outputs | A synthetic marker in a local failed-unit journal did not appear in the alert email or raw journal output, 2026-09-25 |
| Test alert received without journal contents | Delivered; the received email contained neither the marker nor raw journal output, 2026-09-25 |
