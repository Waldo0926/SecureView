# Backup and Recovery

[English](BACKUP_AND_RECOVERY.md) | [Simplified Chinese](BACKUP_AND_RECOVERY.zh-CN.md)

This is the recovery plan for the SecureView staging deployment (issue #56): what is backed up,
how often, how fast it must come back, how long it is kept, and how each claim is tested. It is
sized for what the project is — one FYP team's staging VPS with a small number of users and
graders — not copied from an enterprise template. Weekly provider snapshots stay useful as an
extra layer, but they are not this plan: they live with the same provider, restore the whole VM
rather than one consistent application state, and have never been restore-tested.

The mechanism:

| Piece | What it does |
|---|---|
| `backend/scripts/backup_encrypted.py` | One coordinated backup set: MySQL dump + ciphertext objects + manifest, each sealed to a backup **public** key, shipped off-server |
| `backend/scripts/restore_drill.py` | Clean-host restore and verification, with per-step timings; refuses anything inconsistent |
| `backend/scripts/backup_envelope.py` | RSA-OAEP-SHA256 key wrap + AES-256-GCM streaming envelope |
| `backend/scripts/db_fingerprint.py` | Per-table `CHECKSUM TABLE` + `information_schema` schema fingerprint, to compare two databases |
| `backend/scripts/backup_restore_drill.sh` | End-to-end drill with throwaway keys and accounts; runs in CI (`mysql-gate`) on every PR |
| `backend/scripts/mysql_release_gate.sh` | Migration lock races, checksummed restore, rollback before upgrade, partial-DDL recovery |
| `database/mysql/04-backup-account.sql` | The least-privilege `fyp_backup_user` account |
| `deployment/server/mcs21-offsite-backup.{service,timer}` | Nightly schedule template (not installed by the deploy tooling) |

## 1. Objectives

| Asset | RPO | RTO | Retention |
|---|---|---|---|
| MySQL metadata (all application tables, `alembic_version`) | 24 h (nightly set); plus the existing pre-deploy dump taken by `mcs21-deploy` on every release | Data restore step: 1 h. Whole service on a new host: 4 h | Off-server: every nightly set for 35 days (R2 lifecycle rule on `staging/`, 30-day bucket lock). Pre-deploy dumps: same host, as `mcs21-deploy` keeps them |
| Ciphertext objects (`ENCRYPTED_FILE_DIR`) | 24 h, **in the same set as the metadata** | Same as metadata — restored together or not at all | Same sets as metadata |
| Configuration in git (nginx, systemd units, SQL, deploy scripts) | 0 — every change is a commit | 30 min (redeploy the commit) | Git history |
| Host secrets (`backend.env`: `SECRET_KEY`, DB passwords, SMTP) | Not backed up — regenerated on restore | Inside the 4 h service RTO | None; see §6 |
| Recovery metadata in the database (`recovery_keys` public keys, per-file recovery wrappings) | With the database | With the database | With the database |
| Recovery **private** keys and the backup **private** key | Captured offline when created or rotated; no routine copy | Custodian retrieval, within one working day (§7) | Every historical key, for as long as any file or backup set still needs it |

Why these numbers:

- **24 h RPO.** Staging traffic is bursty and low-volume (the team, testers, graders), not
  continuous production writes. Losing at most a day of uploads, which the uploader still has,
  is acceptable here, and a single nightly job needs no binlog/point-in-time tooling the team
  could not operate. Releases add an extra recovery point because `mcs21-deploy` dumps the
  database before every deploy.
- **1 h data-restore RTO.** Measured restore time is seconds per gigabyte (§5). The budget
  leaves room for pulling a set back from off-server storage (about 100 s/GB at 10 MB/s) and
  for a human following this document carefully.
- **4 h whole-service RTO.** On a brand-new host, the slow steps are human ones: provisioning the
  VM, installing Docker and MySQL, the custodian bringing the offline key, and redeploying.
  Those have **not** been timed end to end on a real VPS (see "Not yet done").
- **35 days of nightly sets off-server.** Recent points cover "we broke something this week";
  a month covers "we noticed it within the month", about a teaching period. The staging
  restore check went six weeks unnoticed, so problems here are found late. An R2 lifecycle rule
  can only expire by age, so it keeps every nightly set for 35 days (about 26 GB, roughly
  US$0.25 a month beyond R2's free 10 GB). A 30-day bucket lock stops anyone, including the
  backup credential on a compromised host, from deleting a set younger than 30 days. `--prune`
  still applies 7 daily + 4 weekly to a local or mounted destination.

## 2. What one backup set contains, and why metadata and objects agree

`backup_encrypted.py` writes one set per run, named by a **manifest id** (UTC timestamp +
random suffix, e.g. `20260924T091500Z-3f9c2a1b`):

```
<dest>/<manifest-id>/db.sql.enc          mysqldump; line 1 is "-- fyp-backup-manifest-id: <id>"
<dest>/<manifest-id>/objects.tar.enc     ciphertext objects; member MANIFEST_ID holds <id>
<dest>/<manifest-id>/manifest.json.enc   <id>, dump window, SHA-256 of every object and artifact
<dest>/<manifest-id>/index.json          plaintext: <id>, artifact SHA-256s, key fingerprint
```

**Consistency mechanism.** The dump is a single InnoDB snapshot (`--single-transaction`).
Every table is InnoDB, so this needs no table locks and no `RELOAD`/`LOCK TABLES` privilege.
The objects are archived *after* the dump. That order is safe because of how the application
writes storage (`FileService`):

- an upload publishes its write-once object **before** its row commits, so every row visible in
  the snapshot already has its object;
- a delete commits `status = 'DELETED'` **before** it unlinks the object, so the only way a row
  that is ACTIVE in the snapshot loses its object is a delete in the seconds between dump and
  archive.

The backup closes that gap by checking, not by hoping. After archiving, it reads every `files`
row that could be ACTIVE in the snapshot: rows created before the dump ended that are either
not DELETED or were deleted after the dump started. Every such row must have its object in the
archive, hashing to `files.encrypted_sha256`. If any does not, the run **fails** and ships
nothing. Such a failure means either a delete raced the backup (re-run it) or storage is
corrupt (investigate).

**Restore-time enforcement.** `restore_drill.py` refuses a set unless:

1. each artifact matches its SHA-256 in `index.json`;
2. each artifact authenticates under the private key **and** this set's manifest id and role.
   These are bound into the AES-GCM associated data, so a `db.sql.enc` from Monday cannot be
   combined with Tuesday's objects even if someone edits `index.json`;
3. the id in the manifest, on the dump's first line, and in the archive's `MANIFEST_ID` member
   all equal the index id, and the dump ends with mysqldump's completion trailer;
4. after loading, every ACTIVE `files` row has its object in the archive with the right
   SHA-256. Objects no row references are left out, so restored metadata references exactly
   the restored object set;
5. the restored `alembic_version` equals the revision recorded at backup time, and
   `alembic check` finds no drift from the models.

If any check fails, the drill drops the database it created, empties the object directory it
filled, and exits non-zero. It also refuses a target database or object directory that is not
empty. CI exercises every one of these refusals (§5).

## 3. Encryption

Each artifact is sealed separately with a fresh random 256-bit data key under AES-256-GCM.
That key is wrapped with RSA-OAEP-SHA256 to a dedicated **backup** RSA key of at least 3072
bits. It is separate from the recovery key and every user key. The host taking backups holds
only the public half, so a compromise of that host or of the off-server storage exposes
ciphertext and nothing that opens it. Nothing unencrypted leaves the private temporary
directory, which is mode 0700 and deleted at the end of the run.

Why not `age` or `gpg`: neither is installed on the staging host or in CI. `cryptography` is
already a pinned backend dependency. `openssl enc` was rejected because it has no
authenticated mode, so a flipped byte would decrypt silently. The format is documented in
`backup_envelope.py`, and unit tests pin its tamper, wrong-key, and wrong-context behaviour.

Create the backup keypair once, on the custodian's offline machine:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -aes-256-cbc -out backup_priv.pem
openssl pkey -in backup_priv.pem -pubout -out backup_pub.pem   # only this goes to the server
```

## 4. Least-privilege credentials and where sets go

**Database.** `database/mysql/04-backup-account.sql` creates `fyp_backup_user` with a
server-generated password, `REQUIRE SSL`, at most two connections, and exactly
`GRANT SELECT ON fyp_secure_file_platform.*`. It is a separate, re-runnable file on purpose.
`02-schema.sql` is a run-once, empty-database installer, and a GRANT there to an account
`01-provision.sql` never creates would abort a fresh install half-way (MySQL error 1410). The
grant is database-level so that a table added by a future release is never silently left out
of backups: mysqldump skips tables it cannot see. `check_runtime_grants.py` connects as this
account in CI and proves it can read every table but cannot INSERT, UPDATE, DELETE, CREATE,
ALTER, DROP, GRANT, LOCK TABLES, FLUSH TABLES, CREATE USER, or read `mysql.*`. A deliberately
widened grant makes that check fail.

**Host.** The systemd template runs the job with its own `backup.env`, which holds only the
`BACKUP_*` values. It never reads the application's `backend.env`, so it cannot see
`SECRET_KEY` or the runtime DB password. The filesystem is read-only except the job's
private temp directory.

**Destination** (`--dest`):

- `user@host:/path` — rsync over SSH. Use a dedicated key restricted on the receiving side
  (for example `rrsync -wo`), so the backup host can add sets but not read or delete them.
- `s3://bucket/prefix` — `aws s3 cp` (set `BACKUP_S3_ENDPOINT_URL` for an S3-compatible
  provider). Use a credential that can only put objects, and enforce retention with a
  lifecycle rule.
- a local directory — what CI and the local drill use. **On one machine this is a stand-in for
  off-server storage, not the real thing.** A mounted remote filesystem is acceptable.

`index.json` is always written last, so a set without it is incomplete by definition. Restore
refuses such a set, and pruning and the freshness check ignore it.

**Failure monitoring.** Any failure exits non-zero with one `backup_encrypted: FAILED -- …`
line. Under systemd the unit enters the failed state (visible in `systemctl --failed` and the
journal). `backup_encrypted.py --check-freshness <dest> --max-age-hours 26` fails when the
newest complete set is too old, and can run from any machine that can see the destination.
The unit's `OnFailure=mcs21-alert@%n.service` emails that failure, with the last 30 journal
lines, to the people in `/etc/fyp-secure-file-platform/alert.env`; the same alert covers the
same-host `mcs21-backup` and `mcs21-backup-verify` units. Setup and testing are in
[RECONCILIATION_RUNBOOK.md §9](RECONCILIATION_RUNBOOK.md#9-alerts).

## 5. Clean-host restore drill and measured timings

Procedure for a real restore onto a new host (the same commands the drill runs):

1. Provision MySQL 8.4 and run `database/mysql/01-provision.sql` (creates the empty database
   and `fyp_user`).
2. Copy the chosen set from off-server storage. The custodian brings `backup_priv.pem` (§7).
3. Restore into the empty database and an empty object directory:
   ```bash
   cd backend
   DB_HOST=127.0.0.1 DB_PORT=3306 ADMIN_DB_USER=root ADMIN_DB_PASSWORD=... \
     .venv/bin/python scripts/restore_drill.py \
       --backup-set /restore/20260924T091500Z-3f9c2a1b --private-key /media/custodian/backup_priv.pem \
       --target-db fyp_secure_file_platform --objects-dir /var/lib/fyp-secure-file-platform/encrypted_files \
       --report restore-report.json
   ```
4. Re-apply the runtime grants (the GRANT block at the end of `02-schema.sql`, which is not
   part of a data dump):
   ```bash
   .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from check_runtime_grants import *; \
     print('\n'.join(extract_grants(SCHEMA_SQL_PATH, PRODUCTION_RUNTIME_USER, PRODUCTION_DATABASE_NAME, 'fyp_user', 'localhost')))" \
     | sudo mysql
   ```
   Then run `03-verify.sql`, write a fresh `backend.env` (§6), deploy, and call
   `POST /audit-logs/verify-chain` to confirm the audit hash chain survived.

**Measured** on 2026-09-24, on a local Apple-silicon laptop with Docker MySQL 8.4.11
(`restore_drill.py` timings; 90 % of seeded files ACTIVE, 10 % DELETED with objects removed):

| Run | Dump | Objects | Backup total | Restore total | Restore breakdown |
|---|---|---|---|---|---|
| CI-sized drill: 200 files × 64 KiB | 131 KB | 180 / 12 MB | 0.18 s | 0.96 s | load DB 0.31 s, objects 0.05 s, verify 0.45 s |
| 1 000 files × 1 MiB, same server | 506 KB | 900 / 945 MB | 6.5 s | 3.96 s | decrypt 0.44 s, load DB 0.46 s, objects 1.53 s, verify 0.68 s |
| **Clean host:** same set onto a second, empty MySQL 8.4 server | 506 KB | 900 / 945 MB | 5.3 s | **4.27 s** | verify ciphertext 0.38 s, decrypt 0.46 s, manifest 0.42 s, load DB 0.76 s, objects 1.55 s, verify 0.67 s |

In the clean-host run the restored database's data and schema digests (`db_fingerprint.py
digest`) matched the source server's exactly, and `diff -r` found the restored object tree
identical to the source. At about 4.5 s/GB of machine time plus transfer, the 1 h data-restore
RTO holds with a wide margin for any dataset this deployment will plausibly have (tens of GB
would still fit). The number that is not measured is the human part of the 4 h whole-service
RTO.

**Staging drill, 2026-09-24 (the real key and a real off-server set).**
`mcs21-offsite-backup.service` on staging wrote set `20260924T141906Z-7c503f93` (24 objects,
738 MB) to Cloudflare R2 in 70.9 s, 67.4 s of it upload. The set was downloaded from R2 on the
VPS (66 s; the R2 token only accepts the VPS's address) and copied to a MacBook (326 s), then
restored there into an empty Docker MySQL 8.4.11 with the custodian's passphrase-protected
key: **6.97 s** in total (verify ciphertext 0.32 s, decrypt 4.49 s, manifest 0.32 s, load DB
0.46 s, objects 0.71 s, verify 0.65 s). Checked independently of the drill script: `CHECKSUM
TABLE` of all 17 restored tables equals the live database's, and the SHA-256 of all 24
restored objects equals the live files'. Transfer, about 6.5 minutes from R2 to a machine off
the VPS, dominates, and still fits the 1 h data-restore RTO.

A restore on a new host needs its own R2 read token: the staging token is limited to the VPS's
IP address, so the account owner creates a read token for the new host in the Cloudflare
dashboard as part of the restore.

CI (`mysql-gate` → "Encrypted backup, clean restore, and refusal drill") runs
`backup_restore_drill.sh` on every pull request. It generates a throwaway RSA key and backup
account inside the job, backs up as that least-privilege account, and checks that the
destination contains no plaintext and no private key. It then restores into a database that
does not exist yet and compares content, schema, and every object. Finally it proves refusal
of a tampered artifact, an artifact from another set, the wrong key, an incomplete set, a set
whose archive lacks an object an ACTIVE row needs, and a non-empty target, and that the backup
itself stops on a row whose object is missing. The restore report (ids, counts, timings only)
is kept as a workflow artifact for 90 days.

## 6. Configuration and host secrets

Everything reproducible lives in git and is restored by redeploying a commit. The host's
`backend.env` is deliberately **not** in the backup: it would put live credentials into every
off-server set. On restore, generate new values: `01-provision.sql` issues a new `fyp_user`
password, `04-backup-account.sql` a new backup password, and write a new `SECRET_KEY`. Rotating
`SECRET_KEY` only ends existing sessions and unexpired email-verification codes (it signs
tokens and HMACs short-lived codes; it encrypts nothing at rest). SMTP credentials come from the
provider's console.

## 7. Recovery-key custody

Verified against the code, not assumed:

- `recovery_keys` stores only `public_key_pem`, fingerprint, size, and status. No column
  anywhere holds a recovery private key. The only private-key columns in the schema belong to
  `encrypted_private_key_bundles`, which holds users' keys encrypted client-side under a key
  derived from each user's passphrase; the server never sees them in plaintext. A unit test
  (`test_backup_scope_holds_no_plaintext_private_key_columns`) fails if that changes.
- `register_recovery_key.py` generates the recovery keypair on the operator's machine, sends
  only the public half, and writes the private key locally (default `recovery_keys/`,
  gitignored). It never touches the database or the object store.
- `backup_encrypted.py` archives only files whose paths are valid storage object keys, and
  **aborts** if anything in the object directory looks like a PEM private key. So even a key
  misplaced there cannot slip into a routine backup.

So recovery private keys are outside the routine online backup by construction.

**Custody, stated honestly (proposed; needs team agreement before the timer is enabled).**
This team has no HSM. The recovery private key and the backup private key are each exported once, passphrase-protected, onto two encrypted USB drives kept
offline in two different places. The named custodian is the **Testing & Deployment Lead**
(currently Shuoxun Wen), and the **Crypto & Security Lead** (currently Tai Chen) is the second
holder. Neither key is ever stored on a networked host, in cloud storage, or in this
repository. Their SHA-256 fingerprints are recorded in the team's private records so a holder
can check a key against what the upload page and `index.json` report. An HSM or cloud KMS
would replace this if the project ever outgrew staging.

**Historical keys.** Registering a new recovery key does not rewrap existing files, so every
retired recovery private key is kept for as long as any file wrapped to it still exists. In
practice that means for the life of the deployment, since there is no tooling yet that proves
no file still uses a key. Every retired backup private key is kept until the last backup set
sealed to it has aged out of retention (about five weeks after rotation). Keys are never
deleted by automation. Deleting one is a written decision by both holders.

## 8. Rollback before a schema upgrade, and partially applied DDL

`mysql_release_gate.sh` exercises both against MySQL 8.4 in CI:

1. **Rollback before upgrade** (`rollback before a schema upgrade` phase). The gate backs up a
   database at `0005`, migrates it to `0006`, and writes a row. It then replaces the migrated
   database with the backup and proves the revision is `0005` again and the data and schema
   fingerprints equal the pre-upgrade ones. Writes made after the upgrade are lost; that is
   the price of rolling back, and why it is a deliberate decision. Re-upgrading from the
   restored state then works.
2. **A multi-revision release interrupted part-way** (release = `0005` + `0006` onto `0004`):
   - *between* revisions (0005 applied and stamped, 0006 not): **forward resume** with
     `migrate.sh upgrade head` is supported and proven;
   - *inside* a revision: MySQL DDL auto-commits per statement, so a process killed after
     0005 drops `ck_files_encryption_envelope` but before it recreates it leaves the
     constraint gone while `alembic_version` still says `0004`. The gate proves forward resume
     then **fails** (MySQL error 3821). It then proves the supported path works: restore the
     pre-release backup (identical fingerprint, revision `0004`) and re-run the whole release.

**Supported path on staging.** Production applies schema changes as reviewed, root-executed
SQL, not Alembic (`docs/DEPLOYMENT.md`), and `mcs21-deploy` dumps the database before each
release. For any partially applied production DDL release the supported recovery is
**backward**: keep the app stopped, restore the pre-release backup, and re-run the complete
release. Forward resume is supported only where Alembic and `migrate.sh` run (development, CI,
disposable databases), and only after an interruption on a revision boundary.

## 9. Finding and restoring one damaged file

Sections 1 to 8 recover the whole service. This one answers a narrower question: *a stored file
was modified; how is it found, and how does the original come back?*

**There is no version history, and none is needed.** A stored ciphertext object is write-once: it
never changes legitimately. So a backup copy whose SHA-256 equals the digest the system recorded
for the file is, byte for byte, the original. The "last known good version" is simply a backup
set that holds the right bytes. The digest that decides is the one written into the audit hash
chain when the file was uploaded (`FILE_UPLOADED.metadata.ciphertext_sha256`), not only the
`files.encrypted_sha256` column, because someone who can rewrite an object can often rewrite
that column as well. Files uploaded before this was recorded have no audit digest and fall back
to the column.

**The "Request recovery" button on My Files is not this.** A recovery request asks a recovery
officer to re-seal the file *key* to the requester's current account key (a lost passphrase, a
replaced key). It cannot put changed bytes back, so on a file the integrity check has flagged the
button is off and the dialog, if reached, answers that an administrator restores the file from
backup. Until PR #226 the server answered "not found" there, which read as if the file had vanished.

### Finding it

| Where | What it does |
|---|---|
| Download | The server hashes the object before streaming it and refuses on a mismatch (existing) |
| **Daily sweep** `scripts/integrity_sweep.py`, `mcs21-integrity-sweep.timer` (05:30 Kuala Lumpur) | Hashes every stored object, least recently checked first; writes `integrity_checks` rows and an audit event for each finding; exits 3 if anything is damaged so the failure alert fires |
| **Admin → Integrity** | Lists damaged files and how much of the store has been checked; "Scan now" verifies a batch of up to 50 files within 20 seconds and says how many remain |

A result of `MODIFIED` is evidence about the bytes and marks the file `CORRUPTED`. `MISSING` and
`ERROR` describe the storage (an unmounted volume, an I/O error) and do not change the file's
status, so a short outage does not condemn intact files. The next passing check heals the status.

The timer is installed **automatically**: after each healthy release `mcs21-deploy` installs and
enables `mcs21-integrity-sweep.timer` from it (a closed list; see
[AUTOMATIC_DEPLOYMENT.md](AUTOMATIC_DEPLOYMENT.md#ops-units-a-release-installs-by-itself)). That
takes effect once the updated `mcs21-deploy` has been installed on the VPS. To install by hand
instead, or to read a first run before relying on it:

```bash
sudo systemd-run --pipe --wait --quiet --uid=fypapp --gid=fypapp \
  --working-directory=/opt/mcs21/current/backend \
  --property=EnvironmentFile=/etc/fyp-secure-file-platform/backend.env \
  /opt/mcs21/current/backend/.venv/bin/python scripts/integrity_sweep.py
R=/opt/mcs21/current/deployment/server
sudo install -m 0644 "$R/mcs21-integrity-sweep.service" "$R/mcs21-integrity-sweep.timer" /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/mcs21-integrity-sweep.service
sudo systemctl daemon-reload && sudo systemctl enable --now mcs21-integrity-sweep.timer
```

### Putting the original back

`backend/scripts/restore_file.py`, run on the server. Admin → Integrity shows the two commands
for the damaged file, and they run as pasted:

```bash
cd /opt/mcs21/current/backend
sudo .venv/bin/python scripts/restore_file.py --file-id <file uuid>            # dry run
sudo .venv/bin/python scripts/restore_file.py --file-id <file uuid> --apply    # write
```

With no `--backup-set` the script uses the **same-host nightly backup** that `mcs21-backup`
writes to `/var/backups/mcs21-daily` (a plaintext tar of the object store, root-only, kept 14
days): newest archive first, each checked against its `.sha256` manifest, the one object read out
and compared with the recorded digest, and an archive that already holds the damaged bytes skipped
for the next older one. No key is needed for that. Run as root it loads
`/etc/fyp-secure-file-platform/backend.env` itself and gives the restored object, the quarantine
copy and the quarantine directory back to the service account. On the staging VPS the dry run
takes about 1.5 s against a 780 MB archive.

For a server whose disk is gone, or whose nightly copies are also suspect, the **encrypted
off-site set** is the fallback, with the **offline backup private key** brought by the custodian
for the duration of the restore:

```bash
.venv/bin/python scripts/restore_file.py --file-id <file uuid> \
    --backup-set /path/to/<manifest-id> --private-key /path/to/backup_priv.pem          # dry run
.venv/bin/python scripts/restore_file.py ... --apply                                      # write
```

The first command changes nothing and reports which backup it would use. With `--apply` it:

1. refuses unless the set's artifacts match `index.json`, decrypt and authenticate under this key
   and this set's manifest id, and the archive matches its manifest;
2. refuses unless the set holds this object **and** its SHA-256 and size equal the recorded ones
   (a set taken before the upload, or one that already held tampered bytes, is not used);
3. copies the damaged bytes to a quarantine directory (`<storage parent>/quarantine`, or
   `--quarantine-dir`), because a tampered object is evidence;
4. writes the original beside the object and renames it into place atomically;
5. if the database digest had been rewritten to match the tampered object, puts the audit-chain
   digest back in `files.encrypted_sha256`;
6. re-verifies the file by the same rule that condemned it, which records a `VALID` check and
   returns the status to `ACTIVE`, and writes `FILE_RESTORED_FROM_BACKUP` to the audit chain.

The off-site private key never goes on the server permanently and there is no web button for
this: the admin page shows what is damaged and the command to run, and the decision stays with a
person who has root.

### Limits, stated plainly

- A file uploaded after the last nightly backup is in no backup and cannot be restored this way.
  The window is the 24 h RPO of §1.
- Decrypting `objects.tar.enc` to take out one object costs the same as decrypting the objects
  half of a full restore, because the archive is one authenticated stream.
- If the backup set itself already holds tampered bytes, the digest check refuses it; try an
  earlier set (35 nights are kept off-server).
- The sweep detects a rewritten digest only for files whose upload recorded the audit digest.
- `scripts/backup_restore_drill.sh` (CI `mysql-gate`) tampers an object, requires the sweep to
  exit 3 and mark it `CORRUPTED`, refuses the wrong key, checks the dry run changes nothing, then
  restores and requires a byte-identical object, a quarantined damaged copy, status `ACTIVE`, and
  the audit row.

## Running it locally

```bash
docker compose up -d mysql                      # or any disposable MySQL 8.4
cd backend
export DB_HOST=127.0.0.1 DB_PORT=3306 ADMIN_DB_USER=root ADMIN_DB_PASSWORD=local_root_password
export SECRET_KEY=local-test-secret-key-at-least-32-chars APP_ENV=test
bash scripts/backup_restore_drill.sh            # encrypted backup -> clean restore -> refusals
DRILL_FILES=1000 DRILL_FILE_BYTES=1048576 bash scripts/backup_restore_drill.sh   # ~1 GB timing run
bash scripts/mysql_release_gate.sh              # lock races, checksummed restore, rollback, partial DDL
```

Both scripts create and drop only databases whose names contain `_test`, and they keep keys,
dumps, and objects in a private temporary directory that is removed on exit.

## Not yet done

- The 4 h whole-service RTO has not been timed end to end on a fresh VPS; only the data
  restore has (§5).
- The rsync destination is wired but untested against a real target. S3 is live on R2.
- ~~`mcs21-deploy`'s pre-deploy backups are never pruned.~~ **Done 2026-10-08** ([PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204)):
  they had grown to 81 dumps and 5.6 GB by 2026-09-24 and 184 sets and 81 GB by 2026-10-08, because
  each one also archives every ciphertext object. They remain plaintext on the same host (root-only,
  0700) as a fast rollback point, not an off-server copy. After a healthy deployment `mcs21-deploy`
  now keeps the newest 10 (`MCS21_KEEP_DEPLOY_BACKUPS`, never fewer than 3). The first run, a forced
  redeploy of `f826165`, removed 175 sets: 81 GB → 7.5 GB, root disk 69 % → 51 % used.

## Staging installation record (2026-09-24)

- Backup account `fyp_backup_user@<docker-gateway>`, created from `04-backup-account.sql` with the
  host changed: MySQL runs in Docker, so TCP connections from the host arrive from the Docker
  gateway `<docker-gateway>`, like every other staging account, and a `localhost` account cannot
  log in. Verified as `fypapp`: TLS (`TLS_AES_256_GCM_SHA384`), reads, and `DELETE` refused.
- `/etc/fyp-secure-file-platform/backup.env` (root, 0600) and `backup_pub.pem` (root:fypapp,
  0640; SHA-256 of the key `4ac77119…`, as recorded in every set's `index.json`).
- `aws` CLI 1.46.1 in a venv at `/opt/awscli`, linked to `/usr/local/bin/aws`. Ubuntu 24.04
  has no `awscli` apt package, and the snap cannot start under the unit's `NoNewPrivileges=true`.
- Destination `s3://<backup-bucket>/staging` on Cloudflare R2. The token has Object Read & Write on
  that bucket only and is limited to the VPS's IP address.
- `mcs21-offsite-backup.timer` enabled (02:30 daily); failures email the address in `alert.env`.
- `/var/lib/fyp-secure-file-platform` holds only `encrypted/` (24 ciphertext objects) and
  `tmp/`; no private key was found there or anywhere else on the host.
- The reinstalled `mcs21-backup-verify` passed for the first time since 2026-08-16.
