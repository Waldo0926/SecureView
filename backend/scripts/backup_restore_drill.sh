#!/usr/bin/env bash
# End-to-end encrypted backup -> clean restore drill (issue #56), for CI and local use.
#
#   1. seed a disposable source database and object directory;
#   2. back it up with backup_encrypted.py as a throwaway account holding exactly the
#      grant in database/mysql/04-backup-account.sql, encrypting to a throwaway RSA
#      public key, into a local directory standing in for off-server storage;
#   3. prove the destination holds no plaintext and no private key;
#   4. restore with restore_drill.py into a database that does not exist yet and an
#      empty object directory, compare against the source (CHECKSUM TABLE + schema +
#      every object hash), and print the measured timings;
#   5. prove restore_drill.py refuses a tampered artifact, an artifact from another
#      backup set, the wrong private key, an incomplete set, and a non-empty target,
#      and that backup_encrypted.py refuses when metadata references a missing object.
#
# Required environment (never printed): DB_HOST, DB_PORT, ADMIN_DB_USER,
# ADMIN_DB_PASSWORD. Optional: DRILL_FILES (200), DRILL_FILE_BYTES (65536),
# MYSQLDUMP_BIN / MYSQL_BIN, DRILL_REPORT (path to keep the restore report).
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND_DIR"

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${ADMIN_DB_USER:?ADMIN_DB_USER is required}"
: "${ADMIN_DB_PASSWORD:?ADMIN_DB_PASSWORD is required}"

DRILL_FILES="${DRILL_FILES:-200}"
DRILL_FILE_BYTES="${DRILL_FILE_BYTES:-65536}"
PYTHON="$BACKEND_DIR/.venv/bin/python"
SOURCE_DB="fyp_backup_drill_source_test"
TARGET_DB="fyp_backup_drill_restore_test"
REFUSE_DB="fyp_backup_drill_refuse_test"
BACKUP_USER="fyp_drill_backup"
BACKUP_HOST="%"
BACKUP_PASSWORD="$(openssl rand -hex 24)"

MYSQL_CLIENT=(mysql --host="$DB_HOST" --port="$DB_PORT" --user="$ADMIN_DB_USER" "--password=$ADMIN_DB_PASSWORD" --protocol=TCP)

WORK="$(mktemp -d)"
chmod 700 "$WORK"
cleanup() {
  "${MYSQL_CLIENT[@]}" --execute "DROP DATABASE IF EXISTS \`${SOURCE_DB}\`; DROP DATABASE IF EXISTS \`${TARGET_DB}\`; DROP DATABASE IF EXISTS \`${REFUSE_DB}\`; DROP USER IF EXISTS '${BACKUP_USER}'@'${BACKUP_HOST}';" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

run_sql() {
  "${MYSQL_CLIENT[@]}" --execute "$1"
}

run_backup() {
  BACKUP_DB_HOST="$DB_HOST" BACKUP_DB_PORT="$DB_PORT" BACKUP_DB_NAME="$SOURCE_DB" \
    BACKUP_DB_USER="$BACKUP_USER" BACKUP_DB_PASSWORD="$BACKUP_PASSWORD" \
    "$PYTHON" scripts/backup_encrypted.py --public-key "$WORK/keys/backup_pub.pem" \
    --objects-dir "$WORK/source-objects" "$@"
}

run_restore() {
  "$PYTHON" scripts/restore_drill.py "$@"
}

# expect_refusal <expected stderr fragment> <restore_drill args...>
expect_refusal() {
  local expected="$1"
  shift
  if run_restore "$@" 2>"$WORK/refusal.log" >/dev/null; then
    echo "FAIL: restore_drill.py accepted a set it should refuse (${expected})" >&2
    exit 1
  fi
  if ! grep -q -- "$expected" "$WORK/refusal.log"; then
    echo "FAIL: restore_drill.py refused, but not for '${expected}':" >&2
    cat "$WORK/refusal.log" >&2
    exit 1
  fi
  if [ "$("${MYSQL_CLIENT[@]}" --batch --skip-column-names --execute "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='${REFUSE_DB}'")" != "0" ]; then
    echo "FAIL: a refused restore left database ${REFUSE_DB} behind" >&2
    exit 1
  fi
  echo "  refused as expected: $(grep -o 'REFUSED -- .*' "$WORK/refusal.log" | cut -c1-140)"
}

# copy_set <source set dir> <new parent>: a writable copy to tamper with
copy_set() {
  mkdir -p "$2"
  cp -R "$1" "$2/"
  echo "$2/$(basename "$1")"
}

# set_index_sha <set dir> <role>: make index.json agree with the artifact on disk,
# so the refusal has to come from decryption or the manifest checks, not the index.
set_index_sha() {
  "$PYTHON" - "$1" "$2" <<'PY'
import hashlib, json, sys
from pathlib import Path
set_dir, role = Path(sys.argv[1]), sys.argv[2]
index = json.loads((set_dir / "index.json").read_text())
name = index["artifacts"][role]["file"]
index["artifacts"][role]["sha256"] = hashlib.sha256((set_dir / name).read_bytes()).hexdigest()
(set_dir / "index.json").write_text(json.dumps(index))
PY
}

echo "== drill: seed the source =="
run_sql "DROP DATABASE IF EXISTS \`${SOURCE_DB}\`; CREATE DATABASE \`${SOURCE_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
run_sql "DROP DATABASE IF EXISTS \`${TARGET_DB}\`; DROP DATABASE IF EXISTS \`${REFUSE_DB}\`;"
DB_USER="$ADMIN_DB_USER" DB_PASSWORD="$ADMIN_DB_PASSWORD" DB_NAME="$SOURCE_DB" \
  "$PYTHON" -m alembic upgrade head >/dev/null 2>&1
mkdir -p "$WORK/source-objects" "$WORK/keys" "$WORK/offsite"
chmod 700 "$WORK/keys"
"$PYTHON" scripts/backup_drill_fixture.py seed "$SOURCE_DB" "$WORK/source-objects" "$DRILL_FILES" "$DRILL_FILE_BYTES"
printf '%s\n' "$BACKUP_PASSWORD" | "$PYTHON" scripts/backup_drill_fixture.py grant-backup "$SOURCE_DB" "$BACKUP_USER" "$BACKUP_HOST"

echo "== drill: throwaway backup keypair (private half stays in the 0700 work dir) =="
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$WORK/keys/backup_priv.pem" 2>/dev/null
openssl pkey -in "$WORK/keys/backup_priv.pem" -pubout -out "$WORK/keys/backup_pub.pem"
chmod 600 "$WORK/keys/backup_priv.pem"

echo "== drill: encrypted backup as the least-privilege account =="
run_backup --dest "$WORK/offsite" | tee "$WORK/backup-1.json"
SET_ONE="$(ls "$WORK/offsite")"
SET_ONE_DIR="$WORK/offsite/$SET_ONE"

echo "== drill: the off-server copy holds no plaintext and no private key =="
if grep -r -l -a -e 'drill-user-0@example.invalid' -e 'CREATE TABLE' -e 'PRIVATE KEY' "$WORK/offsite"; then
  echo "FAIL: plaintext or key material found in the backup destination" >&2
  exit 1
fi
echo "OK: no seeded plaintext, DDL, or private key in the destination"

echo "== drill: clean restore, then compare with the source =="
run_restore --backup-set "$SET_ONE_DIR" --private-key "$WORK/keys/backup_priv.pem" \
  --target-db "$TARGET_DB" --objects-dir "$WORK/restored-objects" \
  --expect-source-db "$SOURCE_DB" --report "$WORK/restore-report.json" >/dev/null
diff -r "$WORK/source-objects" "$WORK/restored-objects"
"$PYTHON" - "$WORK/restore-report.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print(f"OK: restored {report['manifest_id']} at {report['schema_revision']}: "
      f"{report['file_rows']} file rows, {report['objects_restored']} objects, "
      f"dump {report['db_dump_bytes']} B, objects {report['objects_tar_bytes']} B")
print("    content+schema fingerprint matched the source; object tree identical (diff -r)")
for name, seconds in report["timings"].items():
    print(f"    {name:28s} {seconds:8.3f}")
PY
if [ -n "${DRILL_REPORT:-}" ]; then
  cp "$WORK/restore-report.json" "$DRILL_REPORT"
fi

echo "== drill: refusals =="
TAMPERED="$(copy_set "$SET_ONE_DIR" "$WORK/tampered")"
"$PYTHON" - "$TAMPERED/objects.tar.enc" <<'PY'
import sys
path = sys.argv[1]
data = bytearray(open(path, "rb").read())
data[len(data) // 2] ^= 0x01
open(path, "wb").write(bytes(data))
PY
set_index_sha "$TAMPERED" objects
expect_refusal "authentication failed" --backup-set "$TAMPERED" \
  --private-key "$WORK/keys/backup_priv.pem" --target-db "$REFUSE_DB" --objects-dir "$WORK/refuse-objects"

sleep 1
run_backup --dest "$WORK/offsite" >"$WORK/backup-2.json"
SET_TWO="$(ls "$WORK/offsite" | grep -v "^${SET_ONE}$")"
MIXED="$(copy_set "$SET_ONE_DIR" "$WORK/mixed")"
cp "$WORK/offsite/$SET_TWO/db.sql.enc" "$MIXED/db.sql.enc"
set_index_sha "$MIXED" db
expect_refusal "different backup set or role" --backup-set "$MIXED" \
  --private-key "$WORK/keys/backup_priv.pem" --target-db "$REFUSE_DB" --objects-dir "$WORK/refuse-objects"

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$WORK/keys/other_priv.pem" 2>/dev/null
expect_refusal "different backup key" --backup-set "$SET_ONE_DIR" \
  --private-key "$WORK/keys/other_priv.pem" --target-db "$REFUSE_DB" --objects-dir "$WORK/refuse-objects"

INCOMPLETE="$(copy_set "$SET_ONE_DIR" "$WORK/incomplete")"
rm "$INCOMPLETE/index.json"
expect_refusal "index.json is missing" --backup-set "$INCOMPLETE" \
  --private-key "$WORK/keys/backup_priv.pem" --target-db "$REFUSE_DB" --objects-dir "$WORK/refuse-objects"

# A set that authenticates and whose ids all agree, but whose archive lacks one object an
# ACTIVE row needs -- what a buggy backup job could produce. Build it with the drill's own
# key (re-encrypting under the correct manifest id and roles) so only the restore-time
# metadata/object reconciliation can catch it.
INCOMPLETE_OBJECTS="$(copy_set "$SET_ONE_DIR" "$WORK/missing-object")"
"$PYTHON" - "$INCOMPLETE_OBJECTS" "$WORK/keys/backup_priv.pem" "$WORK/keys/backup_pub.pem" <<'PY'
import hashlib, io, json, sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, "scripts")
from backup_encrypted import envelope_context
from backup_envelope import decrypt_file, encrypt_file, load_private_key, load_public_key
set_dir, private, public = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
index = json.loads((set_dir / "index.json").read_text())
mid = index["manifest_id"]
priv, pub = load_private_key(Path(private), None), load_public_key(Path(public))
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for role, name in (("objects", "objects.tar.enc"), ("manifest", "manifest.json.enc")):
        decrypt_file(set_dir / name, tmp / role, priv, envelope_context(mid, role))
    manifest = json.loads((tmp / "manifest").read_text())
    dropped = manifest["objects"].pop(0)["key"]
    out = io.BytesIO()
    with tarfile.open(tmp / "objects") as src, tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as dst:
        for member in src:
            if member.name != f"objects/{dropped}":
                dst.addfile(member, src.extractfile(member))
    (tmp / "objects-new").write_bytes(out.getvalue())
    manifest["objects_tar"] = {"sha256": hashlib.sha256(out.getvalue()).hexdigest(), "bytes": len(out.getvalue())}
    (tmp / "manifest-new").write_text(json.dumps(manifest))
    for role, name, plain in (("objects", "objects.tar.enc", "objects-new"), ("manifest", "manifest.json.enc", "manifest-new")):
        (set_dir / name).unlink()
        encrypt_file(tmp / plain, set_dir / name, pub, envelope_context(mid, role))
        index["artifacts"][role]["sha256"] = hashlib.sha256((set_dir / name).read_bytes()).hexdigest()
(set_dir / "index.json").write_text(json.dumps(index))
PY
expect_refusal "restored metadata references objects this set lacks" --backup-set "$INCOMPLETE_OBJECTS" \
  --private-key "$WORK/keys/backup_priv.pem" --target-db "$REFUSE_DB" --objects-dir "$WORK/refuse-objects"
if [ -n "$(ls -A "$WORK/refuse-objects" 2>/dev/null)" ]; then
  echo "FAIL: the refused restore left objects behind" >&2
  exit 1
fi

SOURCE_DIGEST_BEFORE="$("$PYTHON" scripts/db_fingerprint.py digest "$SOURCE_DB")"
if run_restore --backup-set "$SET_ONE_DIR" --private-key "$WORK/keys/backup_priv.pem" \
    --target-db "$SOURCE_DB" --objects-dir "$WORK/refuse-objects" 2>"$WORK/refusal.log" >/dev/null \
    || ! grep -q "is not empty" "$WORK/refusal.log"; then
  echo "FAIL: restore_drill.py did not refuse a non-empty target database" >&2
  cat "$WORK/refusal.log" >&2
  exit 1
fi
if [ "$("$PYTHON" scripts/db_fingerprint.py digest "$SOURCE_DB")" != "$SOURCE_DIGEST_BEFORE" ]; then
  echo "FAIL: a refused restore modified the non-empty target" >&2
  exit 1
fi
echo "  refused as expected: non-empty target database, left untouched"

# Metadata that references an object the store no longer has must stop the backup itself.
VICTIM="$(find "$WORK/source-objects" -name '*.ciphertext' -print -quit)"
mv "$VICTIM" "$WORK/victim.ciphertext"
if run_backup --dest "$WORK/offsite-missing" 2>"$WORK/backup-refusal.log" >/dev/null; then
  echo "FAIL: backup_encrypted.py shipped a set whose metadata references a missing object" >&2
  exit 1
fi
if ! grep -q "is missing from object storage" "$WORK/backup-refusal.log"; then
  echo "FAIL: backup_encrypted.py failed, but not on the missing object:" >&2
  cat "$WORK/backup-refusal.log" >&2
  exit 1
fi
if [ -n "$(ls -A "$WORK/offsite-missing" 2>/dev/null)" ]; then
  echo "FAIL: the refused backup still left a set at the destination" >&2
  exit 1
fi
mv "$WORK/victim.ciphertext" "$VICTIM"
echo "  refused as expected: backup_encrypted.py stopped on a files row whose object is missing"

# --- one tampered object: detect it, then put the original back from the backup ----------------
# The source database is the "live" deployment here: restore_file.py and integrity_sweep.py read
# the same files rows and object directory the application would.
echo "== drill: a tampered object is detected, then restored from the encrypted backup =="
app_env() {
  env DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" DB_USER="$ADMIN_DB_USER" DB_PASSWORD="$ADMIN_DB_PASSWORD" \
    DB_NAME="$SOURCE_DB" APP_ENV=test ENCRYPTED_FILE_DIR="$WORK/source-objects" \
    TEMP_FILE_DIR="$WORK/source-staging" "$@"
}
sha_of() {
  "$PYTHON" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
}
file_status() {
  "${MYSQL_CLIENT[@]}" --batch --skip-column-names --execute "SELECT status FROM \`${SOURCE_DB}\`.files WHERE file_uuid='$1'"
}
VICTIM="$(find "$WORK/source-objects" -name '*.ciphertext' -print -quit)"
VICTIM_UUID="$(basename "$(dirname "$VICTIM")")"
ORIGINAL_SHA="$(sha_of "$VICTIM")"
mkdir -p "$WORK/source-staging"

app_env "$PYTHON" scripts/integrity_sweep.py >"$WORK/sweep-clean.json"
echo "OK: a sweep of the untouched store found nothing wrong"

printf 'tampered' >>"$VICTIM"
set +e
app_env "$PYTHON" scripts/integrity_sweep.py >"$WORK/sweep-damaged.json" 2>"$WORK/sweep-damaged.err"
SWEEP_STATUS=$?
set -e
if [ "$SWEEP_STATUS" != "3" ] || ! grep -q "$VICTIM_UUID" "$WORK/sweep-damaged.json"; then
  echo "FAIL: the sweep did not report the tampered object (exit $SWEEP_STATUS)" >&2
  cat "$WORK/sweep-damaged.json" "$WORK/sweep-damaged.err" >&2
  exit 1
fi
if [ "$(file_status "$VICTIM_UUID")" != "CORRUPTED" ]; then
  echo "FAIL: the tampered file was not marked CORRUPTED" >&2
  exit 1
fi
echo "OK: the sweep exited 3, named the tampered file and marked it CORRUPTED"

run_restore_file() {
  app_env "$PYTHON" scripts/restore_file.py --file-id "$VICTIM_UUID" --backup-set "$SET_ONE_DIR" "$@"
}
if run_restore_file --private-key "$WORK/keys/other_priv.pem" --apply 2>"$WORK/refusal.log" >/dev/null \
    || ! grep -q "different backup key" "$WORK/refusal.log"; then
  echo "FAIL: restore_file.py did not refuse the wrong private key" >&2
  cat "$WORK/refusal.log" >&2
  exit 1
fi
echo "  refused as expected: wrong backup private key"

run_restore_file --private-key "$WORK/keys/backup_priv.pem" >"$WORK/restore-file-dry.json"
if [ "$(sha_of "$VICTIM")" = "$ORIGINAL_SHA" ] || ! grep -q dry_run_would_restore "$WORK/restore-file-dry.json"; then
  echo "FAIL: the dry run changed the object or did not say what it would do" >&2
  exit 1
fi
echo "OK: the dry run named the backup set and changed nothing"

run_restore_file --private-key "$WORK/keys/backup_priv.pem" --quarantine-dir "$WORK/quarantine" --apply \
  >"$WORK/restore-file.json"
if [ "$(sha_of "$VICTIM")" != "$ORIGINAL_SHA" ]; then
  echo "FAIL: the restored object is not byte-identical to the original" >&2
  exit 1
fi
if [ "$(ls "$WORK/quarantine" | wc -l | tr -d ' ')" != "1" ]; then
  echo "FAIL: the damaged copy was not kept in quarantine" >&2
  exit 1
fi
if [ "$(file_status "$VICTIM_UUID")" != "ACTIVE" ]; then
  echo "FAIL: the restored file is not ACTIVE again" >&2
  exit 1
fi
AUDITED="$("${MYSQL_CLIENT[@]}" --batch --skip-column-names --execute "SELECT COUNT(*) FROM \`${SOURCE_DB}\`.audit_logs WHERE action='FILE_RESTORED_FROM_BACKUP' AND resource_id='$VICTIM_UUID'")"
if [ "$AUDITED" != "1" ]; then
  echo "FAIL: the restore left no FILE_RESTORED_FROM_BACKUP audit row" >&2
  exit 1
fi
app_env "$PYTHON" scripts/integrity_sweep.py >"$WORK/sweep-after.json"
echo "OK: restored byte-for-byte, damaged copy quarantined, file ACTIVE, audited, and a sweep is clean again"

echo "backup_restore_drill.sh: encrypted backup, clean restore, and every refusal check passed"
