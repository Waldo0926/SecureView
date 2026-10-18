#!/usr/bin/env bash
# Exercise the MySQL 8.4 schema-parity release gate described in issue #53,
# beyond what `pytest -m integration` covers, plus the migration-recovery
# paths that docs/BACKUP_AND_RECOVERY.md commits to (issue #56):
#
#   1. a non-empty database refuses a fresh install;
#   2. an interrupted-then-resumed migration is idempotent;
#   3. two concurrent `migrate.sh upgrade head` runs serialize on the named
#      lock -- repeated with randomized start offsets, and each iteration must
#      show one deployer applying and the other waiting then no-opping;
#   4. a pre-migration backup restores with identical content and schema,
#      checked by db_fingerprint.py (CHECKSUM TABLE + information_schema),
#      and a one-row mutation is proven to make that check fail;
#   5. rollback before a schema upgrade: back up, migrate, restore the backup
#      over the migrated database, and prove the old revision, schema, and
#      data are back;
#   6. a partially applied multi-revision DDL release: interrupted *between*
#      revisions resumes forward; interrupted *inside* a revision cannot
#      resume forward (proven) and recovers by restoring the pre-release
#      backup, then re-running the release.
#
# Designed to run both in CI and locally against a disposable MySQL 8.4.
#
# Required environment (never printed): DB_HOST, DB_PORT, ADMIN_DB_USER,
# ADMIN_DB_PASSWORD. Optional: CONCURRENCY_RACE_ITERATIONS (default 8).
#
# Each phase creates and drops its own disposable database so it can never
# collide with the database the main integration test run uses.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND_DIR"

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${ADMIN_DB_USER:?ADMIN_DB_USER is required}"
: "${ADMIN_DB_PASSWORD:?ADMIN_DB_PASSWORD is required}"

# Each iteration is one full 0001->head migration (~4s locally), so 8 keeps
# the added CI time well under a minute.
CONCURRENCY_RACE_ITERATIONS="${CONCURRENCY_RACE_ITERATIONS:-8}"
PYTHON="$BACKEND_DIR/.venv/bin/python"

# Read the release target and migration count from Alembic itself. Keeping either
# value as a literal made this drill reject a valid deployment whenever a new
# migration became head.
read -r HEAD_REVISION REVISION_COUNT < <(
  "$PYTHON" - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory

scripts = ScriptDirectory.from_config(Config("alembic.ini"))
heads = scripts.get_heads()
if len(heads) != 1:
    raise SystemExit(f"mysql release gate requires one Alembic head, found: {heads}")
print(heads[0], sum(1 for _ in scripts.walk_revisions()))
PY
)

MYSQL_CLIENT=(mysql --host="$DB_HOST" --port="$DB_PORT" --user="$ADMIN_DB_USER" "--password=$ADMIN_DB_PASSWORD" --protocol=TCP)
MYSQLDUMP_CLIENT=(mysqldump --host="$DB_HOST" --port="$DB_PORT" --user="$ADMIN_DB_USER" "--password=$ADMIN_DB_PASSWORD" --protocol=TCP --single-transaction --no-tablespaces --routines --triggers)

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

run_sql() {
  "${MYSQL_CLIENT[@]}" --execute "$1"
}

fresh_database() {
  run_sql "DROP DATABASE IF EXISTS \`$1\`;"
  run_sql "CREATE DATABASE \`$1\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
}

# Alembic reads connection details from the app's own Settings object, which
# takes them from these DB_* environment variables (see app/core/config.py).
run_alembic() {
  local database_name="$1"
  shift
  DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" DB_USER="$ADMIN_DB_USER" \
    DB_PASSWORD="$ADMIN_DB_PASSWORD" DB_NAME="$database_name" \
    PYTHON_BIN="$PYTHON" "$PYTHON" -m alembic "$@"
}

run_migrate_sh() {
  local database_name="$1"
  shift
  DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" DB_USER="$ADMIN_DB_USER" \
    DB_PASSWORD="$ADMIN_DB_PASSWORD" DB_NAME="$database_name" \
    PYTHON_BIN="$PYTHON" "$BACKEND_DIR/scripts/migrate.sh" "$@"
}

current_revision() {
  run_alembic "$1" current 2>/dev/null | awk '{print $1}'
}

expect_revision() {
  local database_name="$1" expected="$2" context="$3" actual
  actual="$(current_revision "$database_name")"
  if [ "$actual" != "$expected" ]; then
    echo "FAIL: ${context}: expected revision '${expected}', alembic current reported '${actual}'" >&2
    exit 1
  fi
}

digest() {
  "$PYTHON" scripts/db_fingerprint.py digest "$1"
}

dump_database() {
  "${MYSQLDUMP_CLIENT[@]}" "$1" >"$2"
}

# Restore a dump over an existing database name the way a real rollback
# would: the migrated schema is dropped entirely, not downgraded in place.
restore_over() {
  fresh_database "$1"
  "${MYSQL_CLIENT[@]}" "$1" <"$2"
}

insert_marker_user() {
  local database_name="$1" suffix="$2"
  run_sql "INSERT INTO \`${database_name}\`.\`users\` (user_uuid, username, email, password_hash, role, status, email_verified) VALUES ('00000000-0000-4000-8000-0000000000${suffix}', 'gate-user-${suffix}', 'gate-${suffix}@example.invalid', 'not-a-real-hash', 'USER', 'ACTIVE', 0);"
}

echo "== phase: non-empty database refuses a fresh install =="
GUARD_DB="fyp_release_gate_guard_test"
fresh_database "$GUARD_DB"
# Simulate a database that already holds unrelated, non-Alembic-tracked data:
# the first migration's own CREATE TABLE users collides with it.
run_sql "CREATE TABLE \`${GUARD_DB}\`.\`users\` (id INT PRIMARY KEY);"
if run_alembic "$GUARD_DB" upgrade head; then
  echo "FAIL: alembic upgrade head unexpectedly succeeded against a non-empty, non-Alembic-tracked database" >&2
  exit 1
fi
echo "OK: alembic upgrade head refused the non-empty database instead of corrupting it"
run_sql "DROP DATABASE \`${GUARD_DB}\`;"

echo "== phase: idempotent re-run after a simulated interruption =="
PARTIAL_DB="fyp_release_gate_partial_test"
fresh_database "$PARTIAL_DB"
# Stop partway through the chain -- standing in for a migration process that
# was killed after applying some revisions but not all of them -- then resume.
run_alembic "$PARTIAL_DB" upgrade 0003_client_key_custody
expect_revision "$PARTIAL_DB" 0003_client_key_custody "stop partway"
run_alembic "$PARTIAL_DB" upgrade head
expect_revision "$PARTIAL_DB" "$HEAD_REVISION" "resume to head"
# Re-running upgrade head against an already-current database must be a clean no-op.
run_alembic "$PARTIAL_DB" upgrade head
echo "OK: resumed migration reached head and a repeat upgrade head is a safe no-op"
run_sql "DROP DATABASE \`${PARTIAL_DB}\`;"

echo "== phase: concurrent deployers serialize on the migration lock (${CONCURRENCY_RACE_ITERATIONS} randomized races) =="
LOCK_DB="fyp_release_gate_lock_test"
for iteration in $(seq 1 "$CONCURRENCY_RACE_ITERATIONS"); do
  fresh_database "$LOCK_DB"
  LOG_A="$WORK_DIR/lock-a.log"
  LOG_B="$WORK_DIR/lock-b.log"
  # 0-399ms between the two starts. A full upgrade takes several seconds, so
  # the second deployer always arrives while the first is still migrating,
  # but at a different point in its DDL each time. Either may win the lock.
  OFFSET_MS=$(( RANDOM % 400 ))
  START_OFFSET="$(printf '0.%03d' "$OFFSET_MS")"
  LOCK_NAME="fyp_release_gate_lock_${iteration}_$$"
  MIGRATE_LOCK_NAME="$LOCK_NAME" run_migrate_sh "$LOCK_DB" upgrade head >"$LOG_A" 2>&1 &
  PID_A=$!
  sleep "$START_OFFSET"
  MIGRATE_LOCK_NAME="$LOCK_NAME" run_migrate_sh "$LOCK_DB" upgrade head >"$LOG_B" 2>&1 &
  PID_B=$!
  STATUS_A=0
  STATUS_B=0
  wait "$PID_A" || STATUS_A=$?
  wait "$PID_B" || STATUS_B=$?
  LABEL="iteration ${iteration}/${CONCURRENCY_RACE_ITERATIONS} (offset ${START_OFFSET}s)"
  if [ "$STATUS_A" -ne 0 ] || [ "$STATUS_B" -ne 0 ]; then
    echo "FAIL: ${LABEL}: a concurrent migrate.sh invocation failed instead of waiting cleanly" >&2
    cat "$LOG_A" "$LOG_B" >&2
    exit 1
  fi
  APPLIED_A="$(grep -c 'Running upgrade' "$LOG_A" || true)"
  APPLIED_B="$(grep -c 'Running upgrade' "$LOG_B" || true)"
  WAITED_A="$(grep -c 'is held by another migration' "$LOG_A" || true)"
  WAITED_B="$(grep -c 'is held by another migration' "$LOG_B" || true)"
  # Exactly one deployer applies every revision; the other must have seen
  # the lock held (real contention, not a lucky non-overlap) and then applied
  # nothing at all.
  if [ "$APPLIED_A" -eq "$REVISION_COUNT" ] && [ "$APPLIED_B" -eq 0 ] && [ "$WAITED_B" -eq 1 ] && [ "$WAITED_A" -eq 0 ]; then
    WINNER="first"
  elif [ "$APPLIED_B" -eq "$REVISION_COUNT" ] && [ "$APPLIED_A" -eq 0 ] && [ "$WAITED_A" -eq 1 ] && [ "$WAITED_B" -eq 0 ]; then
    WINNER="second"
  else
    echo "FAIL: ${LABEL}: expected one deployer to apply ${REVISION_COUNT} revisions and the other to wait then apply 0; got applied=${APPLIED_A}/${APPLIED_B} waited=${WAITED_A}/${WAITED_B}" >&2
    cat "$LOG_A" "$LOG_B" >&2
    exit 1
  fi
  expect_revision "$LOCK_DB" "$HEAD_REVISION" "$LABEL"
  run_alembic "$LOCK_DB" check >/dev/null 2>&1 || {
    echo "FAIL: ${LABEL}: alembic check found drift after the race" >&2
    exit 1
  }
  echo "  ${LABEL}: ${WINNER} deployer applied, the other waited then no-opped; schema matches models"
done
echo "OK: ${CONCURRENCY_RACE_ITERATIONS} randomized concurrent upgrades all serialized on GET_LOCK"
run_sql "DROP DATABASE \`${LOCK_DB}\`;"

echo "== phase: restore from a pre-migration backup, full content and schema checksum =="
BACKUP_SOURCE_DB="fyp_release_gate_backup_test"
BACKUP_RESTORE_DB="fyp_release_gate_restore_test"
fresh_database "$BACKUP_SOURCE_DB"
fresh_database "$BACKUP_RESTORE_DB"
run_alembic "$BACKUP_SOURCE_DB" upgrade head
insert_marker_user "$BACKUP_SOURCE_DB" 02
DUMP_FILE="$WORK_DIR/backup.sql"
dump_database "$BACKUP_SOURCE_DB" "$DUMP_FILE"
"${MYSQL_CLIENT[@]}" "$BACKUP_RESTORE_DB" <"$DUMP_FILE"
"$PYTHON" scripts/db_fingerprint.py compare "$BACKUP_SOURCE_DB" "$BACKUP_RESTORE_DB"
echo "OK: the restore matches the source table by table (CHECKSUM TABLE, row counts, columns, indexes, constraints)"

# Prove the comparison is a real content check: change one column of one row
# in the restored copy (same row count) and require the comparison to fail.
run_sql "UPDATE \`${BACKUP_RESTORE_DB}\`.\`users\` SET password_hash = 'tampered-after-restore' WHERE user_uuid = '00000000-0000-4000-8000-000000000002';"
if "$PYTHON" scripts/db_fingerprint.py compare "$BACKUP_SOURCE_DB" "$BACKUP_RESTORE_DB" 2>"$WORK_DIR/tamper.log"; then
  echo "FAIL: mutating one row after restore did not change the checksum -- the comparison is not a real content check" >&2
  exit 1
fi
if ! grep -q 'users: content checksum differs with equal row counts' "$WORK_DIR/tamper.log"; then
  echo "FAIL: the comparison failed, but not because of the mutated users row:" >&2
  cat "$WORK_DIR/tamper.log" >&2
  exit 1
fi
echo "OK: a one-row mutation with an unchanged row count is detected (users: content checksum differs)"
run_sql "DROP DATABASE \`${BACKUP_SOURCE_DB}\`;"
run_sql "DROP DATABASE \`${BACKUP_RESTORE_DB}\`;"

echo "== phase: rollback before a schema upgrade restores the old revision, schema, and data =="
ROLLBACK_DB="fyp_release_gate_rollback_test"
fresh_database "$ROLLBACK_DB"
run_alembic "$ROLLBACK_DB" upgrade 0005_selectable_aes_key_length
insert_marker_user "$ROLLBACK_DB" 04
PRE_DIGEST="$(digest "$ROLLBACK_DB")"
ROLLBACK_DUMP="$WORK_DIR/pre-upgrade.sql"
dump_database "$ROLLBACK_DB" "$ROLLBACK_DUMP"
# Ship the release, and let the application write after it.
run_alembic "$ROLLBACK_DB" upgrade head
expect_revision "$ROLLBACK_DB" "$HEAD_REVISION" "release applied"
insert_marker_user "$ROLLBACK_DB" 05
POST_DIGEST="$(digest "$ROLLBACK_DB")"
if [ "${POST_DIGEST#* }" = "${PRE_DIGEST#* }" ]; then
  echo "FAIL: the upgrade did not change the schema fingerprint, so restoring would prove nothing" >&2
  exit 1
fi
# Decide not to ship: replace the migrated database with the backup.
restore_over "$ROLLBACK_DB" "$ROLLBACK_DUMP"
expect_revision "$ROLLBACK_DB" 0005_selectable_aes_key_length "after rollback restore"
RESTORED_DIGEST="$(digest "$ROLLBACK_DB")"
if [ "$RESTORED_DIGEST" != "$PRE_DIGEST" ]; then
  echo "FAIL: rollback restore does not match the pre-upgrade database (${RESTORED_DIGEST} != ${PRE_DIGEST})" >&2
  exit 1
fi
# The fixed release can then be re-applied from the restored state.
run_alembic "$ROLLBACK_DB" upgrade head
run_alembic "$ROLLBACK_DB" check
echo "OK: restoring the pre-upgrade backup returned the database to 0005 with identical data and schema (writes made after the upgrade are discarded, as documented), and re-upgrading works"
run_sql "DROP DATABASE \`${ROLLBACK_DB}\`;"

echo "== phase: multi-revision release interrupted between revisions resumes forward =="
# The release under test is every revision after 0004, deployed onto a database at 0004.
BETWEEN_DB="fyp_release_gate_between_test"
fresh_database "$BETWEEN_DB"
run_alembic "$BETWEEN_DB" upgrade 0004_email_verification_codes
insert_marker_user "$BETWEEN_DB" 06
# The deploy dies after 0005 was fully applied and stamped, before later revisions.
run_alembic "$BETWEEN_DB" upgrade 0005_selectable_aes_key_length
expect_revision "$BETWEEN_DB" 0005_selectable_aes_key_length "interrupted between revisions"
run_migrate_sh "$BETWEEN_DB" upgrade head
expect_revision "$BETWEEN_DB" "$HEAD_REVISION" "forward resume"
run_alembic "$BETWEEN_DB" check
echo "OK: a release interrupted on a revision boundary resumed forward to head, and alembic check agrees"
run_sql "DROP DATABASE \`${BETWEEN_DB}\`;"

echo "== phase: multi-revision release interrupted inside a revision recovers by restoring backward =="
INSIDE_DB="fyp_release_gate_inside_test"
fresh_database "$INSIDE_DB"
run_alembic "$INSIDE_DB" upgrade 0004_email_verification_codes
insert_marker_user "$INSIDE_DB" 07
INSIDE_PRE_DIGEST="$(digest "$INSIDE_DB")"
INSIDE_DUMP="$WORK_DIR/pre-release.sql"
dump_database "$INSIDE_DB" "$INSIDE_DUMP"
# MySQL DDL auto-commits statement by statement. 0005's upgrade() first
# drops ck_files_encryption_envelope, then recreates it wider, then stamps
# the version. A process killed between the first two statements leaves the
# constraint gone while alembic_version still says 0004. Reproduce exactly
# that state with the same statement Alembic emits.
run_sql "ALTER TABLE \`${INSIDE_DB}\`.\`files\` DROP CHECK \`ck_files_encryption_envelope\`;"
expect_revision "$INSIDE_DB" 0004_email_verification_codes "partial DDL left the stamp behind"
if run_migrate_sh "$INSIDE_DB" upgrade head >"$WORK_DIR/inside-resume.log" 2>&1; then
  echo "FAIL: forward resume over a half-applied revision unexpectedly succeeded; the documented recovery path is wrong" >&2
  exit 1
fi
if ! grep -q "ck_files_encryption_envelope" "$WORK_DIR/inside-resume.log"; then
  echo "FAIL: forward resume failed, but not on the half-dropped constraint:" >&2
  cat "$WORK_DIR/inside-resume.log" >&2
  exit 1
fi
echo "  forward resume refused as expected (0005 cannot drop a constraint that is already gone)"
restore_over "$INSIDE_DB" "$INSIDE_DUMP"
expect_revision "$INSIDE_DB" 0004_email_verification_codes "after restoring the pre-release backup"
if [ "$(digest "$INSIDE_DB")" != "$INSIDE_PRE_DIGEST" ]; then
  echo "FAIL: restoring the pre-release backup did not reproduce the pre-release database" >&2
  exit 1
fi
run_migrate_sh "$INSIDE_DB" upgrade head
expect_revision "$INSIDE_DB" "$HEAD_REVISION" "re-running the release after restore"
run_alembic "$INSIDE_DB" check
echo "OK: a release interrupted mid-revision was recovered by restoring the pre-release backup (identical fingerprint) and re-running the release to head"
run_sql "DROP DATABASE \`${INSIDE_DB}\`;"

echo "mysql_release_gate.sh: all phases passed"
