# Reconciliation Runbook

[English](RECONCILIATION_RUNBOOK.md) | [Simplified Chinese](RECONCILIATION_RUNBOOK.zh-CN.md)

This is how the staging reconciliation job is installed, reviewed, enabled, run by hand,
disabled, rolled back, and watched (issue #57). The job is `backend/scripts/reconcile.py`. It
removes database rows and storage entries that nothing will ever read again. Because it
deletes, it is enabled only after an operator has read a report-only run on the real host and
recorded it in [§11](#11-installation-record).

| Piece | What it does |
|---|---|
| `backend/scripts/reconcile.py` | Report-only by default; `--apply` deletes. Counts every category on both sides of its cutoff. Refuses unusual volume |
| `deployment/server/mcs21-reconcile.{service,timer}` | Daily at 05:00 Asia/Kuala_Lumpur as `fypapp`, only after a fresh same-host backup |
| `deployment/server/mcs21-alert` + `mcs21-alert@.service` | Emails a person when any ops unit fails |
| `deployment/server/mcs21-backup.service.d/alert.conf`, `mcs21-backup-verify.service.d/alert.conf` | Alert drop-ins for the two server-only backup units |
| `deployment/server/mcs21-backup`, `mcs21-backup-verify` | The same-host daily backup and weekly restore check, now under version control |

None of these is installed by `mcs21-deploy`. They are copied by hand, as described in §4.

## 1. What it deletes

The row cutoff is 30 days (`--retain-days`). The storage grace is 60 minutes
(`--storage-grace-minutes`).

| Category | Removed when | Why it is dead |
|---|---|---|
| `session_refresh_tokens` | expired, consumed, or revoked before the cutoff, or belonging to a session removed in the same run | Single use; a consumed or expired token is never honoured again |
| `user_sessions` | `absolute_expires_at` or `revoked_at` before the cutoff | Expiry is decided from timestamps at request time, so a lapsed session is already unusable |
| `auth_login_throttles` | window started before the cutoff **and** any block ended before the cutoff | A bucket that still blocks someone is never removed; deleting it would lift a lockout |
| `email_verification_codes` | `expires_at` before the cutoff | Only a keyed digest was stored, and an expired code is rejected anyway |
| Orphaned ciphertext objects | `*.ciphertext` under `ENCRYPTED_FILE_DIR` that no non-`DELETED` `files` row names, older than the grace | Left by a request that died between publish and commit, or by a delete whose unlink failed |
| Stale staged uploads | `*.staging` in `TEMP_FILE_DIR` older than the grace | An upload that never finished |
| Empty per-file directories | empty `ENCRYPTED_FILE_DIR/<file_id>/` older than the grace | Left behind after its object was removed |

On staging, `ENCRYPTED_FILE_DIR=/var/lib/fyp-secure-file-platform/encrypted` and
`TEMP_FILE_DIR=/var/lib/fyp-secure-file-platform/tmp`. Both are `0700 fypapp`.

An empty directory gets the same grace as an object. `publish` in
`app/services/file_storage_service.py` creates `<file_id>/` and then hard-links the object into
it, and a client can retry an upload with the same `file_id`. Removing a new directory between
those two steps would fail a live upload. Unlinking a directory's last object refreshes its
mtime, so a directory emptied by one run is collected by the next.

## 2. What it never touches, and the evidence

| Never touched | Evidence |
|---|---|
| `audit_logs`, `audit_chain_heads` | The runtime grant (`database/mysql/02-schema.sql`) is `SELECT, INSERT` on `audit_logs` and `SELECT, UPDATE (last_log_id, current_hash, updated_at)` on `audit_chain_heads`. Connected as `fyp_user`, the job **cannot** delete audit evidence, even with a bug |
| `users`, `user_keys`, `user_key_protection_profiles`, `encrypted_private_key_bundles`, `recovery_keys` (key custody) | Never named by the script. The only foreign key into the reconciled tables is `session_refresh_tokens.session_id → user_sessions ON DELETE CASCADE`. Nothing cascades from the reconciled tables into audit, key, or recovery tables |
| `recovery_requests` | Never named; an expired request is accountability evidence |
| `files`, `file_folders`, `file_access_grants`, `file_key_wrappings`, `integrity_checks` (live authorization) | `files` is read to learn which objects are live, and never written. An object a live row names is kept however old |
| Access that should be gone | An access token authenticates only by joining `user_sessions.access_token_hash` (`app/repositories/auth_repository.py`, `get_access_principal`). A deleted session row means the token is rejected, so deletion can only reduce access, never revive it |

The tests enforce this. `backend/tests/unit/test_reconcile.py` compiles every statement the
job sends. `backend/tests/integration/test_reconcile_mysql.py` captures every statement MySQL
receives during a report run and an apply run. Both fail if any statement names one of the
tables above, or if a write targets anything but the four reconciled tables. The MySQL test
also checks that the `audit_logs` count, the chain head, and the `users` count are unchanged,
and that a 90-day-old object with a live row survives.

## 3. Safeguards built into the schedule

- **A rollback point first.** `mcs21-backup.timer` runs at 04:15 (up to 20 minutes of random
  delay). `mcs21-reconcile.timer` runs at 05:00. Before deleting anything, the service waits on
  `/run/lock/mcs21-backup.lock` and **refuses to start** unless a completed
  `/var/backups/mcs21-daily` set is less than 3 hours old. Anything old enough to delete at
  05:00 (older than 60 minutes) was created before 04:00, so it is in that morning's backup.
  `After=mcs21-backup.service` keeps that order when both catch up after downtime.
- **Volume guard.** With `--apply`, a run that would remove more than `--max-deletions` (1000)
  entries in total, or more than `--max-object-deletions` (10) ciphertext objects, deletes
  **nothing**, prints why, and exits with status **3**. The unit then fails and the alert
  fires. Why these numbers: the staging store holds about two dozen objects (about 738 MB), and
  orphans only come from a crashed request, so more than ten in one day means a wrong directory
  or database, the case where the job would otherwise empty the store. Rows accrue at about one
  session per sign-in plus one refresh token per half hour of activity. A handful of testers
  and the E2E suites make tens to a few hundred a day, and a daily run removes about one day's
  worth. A thousand is several days of that. Report-only runs over a limit only print a
  `WARNING`.
- **Idempotent.** Deletion conditions depend only on timestamps and on what is live. A second
  run straight after the first finds nothing (proven by
  `test_apply_removes_only_what_crossed_and_a_second_run_finds_nothing`).
- **Ordering.** All four row categories are deleted in one transaction. Storage is touched only
  after that commit, so a crash mid-run leaves either every row deletion or none.

## 4. Install (once, after the pull request is merged and deployed)

Run on the staging host. `R` is the deployed release, so these files are the merged, reviewed
ones.

```bash
R=/opt/mcs21/current
cat "$R/.mcs21-release"          # must be the merge commit of the #57 pull request

# The tracked copies differ from what runs today only as reviewed: header comments, and
# the backup-verify fix.
sudo diff -u /usr/local/sbin/mcs21-backup "$R/deployment/server/mcs21-backup"
sudo diff -u /usr/local/sbin/mcs21-backup-verify "$R/deployment/server/mcs21-backup-verify"

sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-backup"        /usr/local/sbin/mcs21-backup
sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-backup-verify" /usr/local/sbin/mcs21-backup-verify
sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-alert"         /usr/local/sbin/mcs21-alert

sudo install -o root -g root -m 0644 "$R/deployment/server/mcs21-alert@.service" \
  "$R/deployment/server/mcs21-reconcile.service" "$R/deployment/server/mcs21-reconcile.timer" \
  /etc/systemd/system/
sudo install -D -o root -g root -m 0644 "$R/deployment/server/mcs21-backup.service.d/alert.conf" \
  /etc/systemd/system/mcs21-backup.service.d/alert.conf
sudo install -D -o root -g root -m 0644 "$R/deployment/server/mcs21-backup-verify.service.d/alert.conf" \
  /etc/systemd/system/mcs21-backup-verify.service.d/alert.conf
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/mcs21-reconcile.service \
  /etc/systemd/system/mcs21-reconcile.timer
```

`mcs21-offsite-backup.service` (issue #56) already carries `OnFailure=` and alerts as soon as
it is installed.

Then set up and test the alert (§9), and confirm the fixed restore check passes. It has
failed every week since 2026-08-16 because it expected schema `0002`:

```bash
sudo systemctl start mcs21-backup-verify.service      # a few minutes
sudo journalctl -u mcs21-backup-verify.service -n 5 --no-pager
# expect: "MCS21 backup restore verification passed: mcs21-db-<stamp>.sql.gz"
```

## 5. Report-only run (dry run)

This deletes nothing. It runs as `fypapp`, with the app's environment, exactly like the unit.
The output holds counts and cutoffs only, with no token hashes, emails, or file names, so it
can be kept and pasted into the issue.

```bash
sudo install -d -o root -g root -m 0750 /var/log/mcs21-reconcile
sudo systemd-run --pipe --wait --quiet --uid=fypapp --gid=fypapp \
  --working-directory=/opt/mcs21/current/backend \
  --property=EnvironmentFile=/etc/fyp-secure-file-platform/backend.env \
  /opt/mcs21/current/backend/.venv/bin/python scripts/reconcile.py \
  | sudo tee "/var/log/mcs21-reconcile/report-only-$(date +%Y%m%d).txt"
```

Output columns:

- `eligible`: would be removed now.
- `crossed last 7d`: of those, how many crossed the cutoff in the last seven days (just past the
  boundary).
- `crosses next 7d`: kept today, but will cross within the next seven days (just inside the
  boundary). For storage rows (`*`), this counts unreferenced entries still inside the
  60-minute grace.

## 6. Reviewing both sides of every boundary

Do this before enabling the timer, and record the result in §11.

1. **Rows.** For each row category, `crossed last 7d` and `crosses next 7d` should be the same
   order of magnitude: a week of ordinary sign-ins from about five weeks ago. Large asymmetry
   points to a clock or timezone problem; check `timedatectl`. `lapsed throttle buckets` must
   never include a bucket that still blocks someone. The predicate excludes it, and the MySQL
   test proves that.
2. **Cross-check the rows independently** (read-only, as the MySQL root inside the container,
   counts only; times are naive UTC):

   ```bash
   sudo docker exec mcs21-mysql sh -c 'MYSQL_PWD=$(cat /run/secrets/mysql-root-password) mysql -uroot --protocol=socket fyp_secure_file_platform -e "
     SET @c = UTC_TIMESTAMP() - INTERVAL 30 DAY, @w = 7;
     SELECT what, SUM(t < @c) eligible,
            SUM(t >= @c - INTERVAL @w DAY AND t < @c) crossed_7d,
            SUM(t >= @c AND t < @c + INTERVAL @w DAY) crosses_7d
     FROM (
       SELECT \"sessions\" what, LEAST(absolute_expires_at, COALESCE(revoked_at, absolute_expires_at)) t FROM user_sessions
       UNION ALL SELECT \"codes\", expires_at FROM email_verification_codes
     ) lapsed GROUP BY what;"'
   ```

   The session and code lines should match the script's `expired sessions` and
   `expired verification codes` lines exactly (give or take rows crossing between the runs).
   The script's refresh-token count is higher than a naive query, because it also includes
   the tokens of sessions being removed.
3. **Objects.** If `orphaned ciphertext objects` is non-zero, list the orphans and check each
   before enabling. Object keys are random UUIDs, not file names, but keep the lists
   root-only and do not paste them into the issue:

   ```bash
   sudo -i
   cd /var/lib/fyp-secure-file-platform/encrypted
   find . -name '*.ciphertext' | sed 's#^\./##' | sort > /root/objects.txt
   docker exec mcs21-mysql sh -c 'MYSQL_PWD=$(cat /run/secrets/mysql-root-password) mysql -uroot --protocol=socket -N fyp_secure_file_platform -e "SELECT storage_object_key FROM files WHERE status <> \"DELETED\" ORDER BY 1"' | sort > /root/live.txt
   comm -23 /root/objects.txt /root/live.txt      # unreferenced: the report's eligible + inside-grace objects
   comm -13 /root/objects.txt /root/live.txt      # live rows without an object: investigate, never ignore
   ```

   For each orphan, `SELECT file_uuid, status FROM files WHERE file_uuid = '<file_id>'` should
   return no row or a `DELETED` row. Any other result stops the rollout.
4. **Volume.** If the report ends in `WARNING: ... exceed --max-deletions`, it is the first run's
   backlog. Clear it once by hand (§7) and do not raise the unit's limit.

## 7. Enable, run by hand, disable

```bash
# Enable (only after §6 is recorded)
sudo systemctl enable --now mcs21-reconcile.timer
systemctl list-timers mcs21-backup.timer mcs21-reconcile.timer

# Run the unit now, with all its guards (take a fresh backup first; the unit requires one < 3 h old)
sudo systemctl start mcs21-backup.service
sudo systemctl start mcs21-reconcile.service
sudo journalctl -u mcs21-reconcile.service -n 40 --no-pager

# One-off backlog clearance after reading the report: fresh backup, then an explicit limit
sudo systemctl start mcs21-backup.service
sudo systemd-run --pipe --wait --quiet --uid=fypapp --gid=fypapp \
  --working-directory=/opt/mcs21/current/backend \
  --property=EnvironmentFile=/etc/fyp-secure-file-platform/backend.env \
  /opt/mcs21/current/backend/.venv/bin/python scripts/reconcile.py --apply --max-deletions <reviewed total>

# Idempotency check: the same report-only command as §5 straight afterwards shows 0 eligible

# Disable
sudo systemctl disable --now mcs21-reconcile.timer
sudo systemctl stop mcs21-reconcile.service     # only if a run is in progress
```

Never raise `--max-object-deletions` to clear orphans. More than ten orphans is an incident
(§10), not a backlog.

## 8. Rollback

Deletions are irreversible. The rollback point is the `/var/backups/mcs21-daily` set written
before the run: `mcs21-db-<stamp>.sql.gz`, `mcs21-files-<stamp>.tar.gz`, and
`mcs21-<stamp>.sha256`. Sets are kept for 14 days, so act within that window.

| Deleted | Needs restoring? |
|---|---|
| Expired/revoked sessions, refresh tokens, verification codes | **No.** They were already unusable. Restoring them grants nothing, and the user signs in again |
| Lapsed throttle buckets | No. A bucket is removed only after its window and any block have lapsed |
| An orphaned ciphertext object that was actually needed | **Yes.** This is the only category where a wrong deletion loses user data |

Restoring one object (as root):

```bash
cd /var/backups/mcs21-daily
sha256sum --check mcs21-<stamp>.sha256
tar -tzf mcs21-files-<stamp>.tar.gz | grep '<file_id>/'
tar -xzf mcs21-files-<stamp>.tar.gz -C /var/lib/fyp-secure-file-platform --keep-old-files \
  './encrypted/<file_id>/<object>.ciphertext'
chown -R fypapp:fypapp '/var/lib/fyp-secure-file-platform/encrypted/<file_id>'
sha256sum '/var/lib/fyp-secure-file-platform/encrypted/<file_id>/<object>.ciphertext'
# must equal files.encrypted_sha256 for that row; then download it through the app
```

What cannot be recovered: an object created after the backup that preceded the run. Scheduled
runs cannot delete such an object (§3), and manual runs take a fresh backup first (§7). If a
row in a reconciled table ever has to come back, restore the dump into a disposable container,
as `mcs21-backup-verify` does, and copy the specific rows. Never load the dump over the live
database for this: that would roll back every other table, the audit chain included.

## 9. Alerts

`mcs21-alert@<unit>.service` emails the failed unit's name, the host, the time, its
`Result`/`ExecMainStatus`, and the last 30 journal lines. Mail goes through the application's
Resend account (`RESEND_API_KEY`, `EMAIL_FROM_ADDRESS`, `EMAIL_FROM_NAME` from `backend.env`).
Recipients come from a separate root-only file. The script parses only those keys (it never
sources either file), and passes the API key to `curl` from a `0600` header file, never on a
command line. The mail provider's response body is never logged.

```bash
sudo install -o root -g root -m 0600 /dev/null /etc/fyp-secure-file-platform/alert.env
sudoedit /etc/fyp-secure-file-platform/alert.env
#   ALERT_EMAIL_TO=first.person@example.com,second.person@example.com
sudo systemctl start mcs21-alert@test.service
sudo journalctl -u mcs21-alert@test.service -n 5 --no-pager    # expect "sent (HTTP 200)"
```

Confirm the test mail actually arrives in each inbox. Units that alert: `mcs21-reconcile`,
`mcs21-backup`, `mcs21-backup-verify`, and `mcs21-offsite-backup`. A failed alert has no alert
of its own (it would loop). It shows in `systemctl --failed` and
`journalctl -u 'mcs21-alert@*'`.

## 10. Incident procedure (an alert arrived)

1. Read the subject for the unit, then run `systemctl status <unit>` and
   `journalctl -u <unit> -n 100 --no-pager`.
2. **`mcs21-reconcile.service`:**
   - `ExecMainStatus=3`: the volume guard refused. **Nothing was deleted.** Read the report in
     the journal, then check the clock (`timedatectl`), `ENCRYPTED_FILE_DIR` and `DB_*` in
     `backend.env`, and whether a deploy or migration just ran. For orphan objects, run §6
     step 3. If the volume is genuine (for example an E2E burst), clear it once by hand (§7).
     Otherwise disable the timer and open an issue.
   - "no mcs21-daily backup from the last 3 hours": the backup failed or is late. Nothing was
     deleted. Fix the backup first; its own alert usually arrives too.
   - A Python traceback (database unreachable, and so on): row deletions are one transaction,
     and storage is touched only after it commits. Fix the cause, then run by hand (§7).
   - Someone reports a missing file: `systemctl disable --now mcs21-reconcile.timer`, keep the
     journal, restore per §8, and open an incident issue linking #57.
3. **`mcs21-backup.service`:** check disk space (`df -h /var/backups`), `docker ps` for
   `mcs21-mysql`, then `systemctl start mcs21-backup.service`. Reconciliation refuses to run
   until this succeeds.
4. **`mcs21-backup-verify.service`:**
   - "structural verification": the restored schema differs from the deployed release.
   - "Live database is at X but the deployed release head is Y": a deploy or migration is
     half-done. Finish it (docs/DEPLOYMENT.md), then rerun.
   - "CHECK TABLE": treat the backup as unusable and escalate.
5. **`mcs21-offsite-backup.service`:** follow docs/BACKUP_AND_RECOVERY.md.
6. Record what happened, and what was done, in the relevant issue.

## 11. Installation record

Fill this in on the host. Do not mark #57 done until every line is filled.

| Item | Value |
|---|---|
| Release SHA installed (`/opt/mcs21/current/.mcs21-release`) | `1c0dcf01ff24606df78a06a8c4eba6a250e8c7f2` (the alert-unit fix from #86, `3e7b7f6`, installed afterwards) |
| Test alert received by (names, date) | 2026-09-24: `mcs21-alert@test` and a real-unit alert to Shuoxun Wen's address, both accepted by Resend (HTTP 200); receipt to be confirmed |
| `mcs21-backup-verify` passing again (date, backup stamp) | 2026-09-24, `mcs21-db-20260923T202022Z.sql.gz` — first pass since 2026-08-16 |
| Report-only run: date/time (UTC) and file in `/var/log/mcs21-reconcile/` | 2026-09-24 14:10 UTC, `report-only-20260924-2210.txt` |
| Report-only totals: eligible / crossed last 7d / crosses next 7d, per category | 43 eligible. Refresh tokens 3/3/60, sessions 3/3/58, throttle buckets 27/25/11, verification codes 10/10/4, storage 0/0/0. Session and code counts matched the independent §6 query exactly; the next-7-days wave is the first week of staging data (from 2026-08-20) reaching 30 days, not a clock fault (clock NTP-synchronised). |
| Orphan objects reviewed (count, and every one confirmed unreferenced) | 0. 24 objects on disk, 24 live rows, none unreferenced, no live row without an object. |
| Backlog cleared by hand? (limit used, date) | Not needed: 43 is under the 1000 limit. |
| Second report-only run shows 0 eligible (idempotency) | `<...>` |
| Reviewer | Shuoxun Wen |
| Timer enabled (date, `systemctl list-timers` next run) | 2026-09-24; next run 2026-09-25 05:00 +08 |
| First scheduled run result (journal excerpt, date) | `<...>` |
