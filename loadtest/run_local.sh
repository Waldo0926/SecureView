#!/usr/bin/env bash
# Prove the load tool end to end against a disposable local stack, without touching staging.
#
#   DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=root DB_PASSWORD=... DB_NAME=fyp_loadtest_test \
#     bash loadtest/run_local.sh
#
# It migrates the schema, starts the unmodified API (backend/tests/e2e/live_server.py), registers
# a recovery key through the admin route, seeds load-test accounts with
# backend/scripts/seed_load_users.py, runs every scenario at a small size, writes the report, and
# deletes the accounts through the API. The numbers it produces describe this laptop, not the
# server: the point is that the tool, the accounts and the report all work before the real run.
#
# Optional: LOAD_USERS (default 7: `sizes` needs one owner per file type plus a recipient), LOAD_PORT (default 8010), LOAD_RESULTS (default
# ./loadtest-results), LOAD_QUICK=1 for an even shorter run.
set -euo pipefail

LOADTEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$LOADTEST_DIR/../backend" && pwd)"
BACKEND_PY="${BACKEND_PY:-$BACKEND_DIR/.venv/bin/python}"
LOAD_PY="${LOAD_PY:-$LOADTEST_DIR/.venv/bin/python}"

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:?DB_NAME is required}"
case "$DB_NAME" in
  *_test*) ;;
  *) echo "DB_NAME must contain _test: this run writes accounts and files" >&2; exit 2 ;;
esac

LOAD_USERS="${LOAD_USERS:-7}"
LOAD_PORT="${LOAD_PORT:-8010}"
RESULTS="${LOAD_RESULTS:-$PWD/loadtest-results}"
mkdir -p "$RESULTS"
RESULTS="$(cd "$RESULTS" && pwd)"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcs21-load.XXXXXX")"
SERVER_PID=""
ACCOUNTS="$WORK_DIR/accounts.json"
API="http://127.0.0.1:$LOAD_PORT/api/v1"
cleanup() {
  if [ -f "$ACCOUNTS" ] && [ -n "$SERVER_PID" ]; then
    echo "== delete the load-test accounts =="
    (cd "$LOADTEST_DIR" && "$LOAD_PY" -m secureview_load --base-url "$API" --accounts "$ACCOUNTS" cleanup) || true
  fi
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  # The API log holds no secrets (no tokens, no keys) and is what explains a 500.
  [ -f "$WORK_DIR/server.log" ] && cp "$WORK_DIR/server.log" "$RESULTS/server.log"
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

export APP_ENV=test APP_DEBUG=false APP_DOCS_ENABLED=false EMAIL_PROVIDER=console
export SECRET_KEY="${SECRET_KEY:-$("$BACKEND_PY" -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export ENCRYPTED_FILE_DIR="$WORK_DIR/objects" TEMP_FILE_DIR="$WORK_DIR/staging"
export E2E_MAILBOX_DIR="$WORK_DIR/mailbox"
export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
mkdir -p "$E2E_MAILBOX_DIR"

secret() { "$BACKEND_PY" -c 'import secrets; print("Aa1!" + secrets.token_urlsafe(24))'; }
RUN_ID="$("$BACKEND_PY" -c 'import secrets; print(secrets.token_hex(3))')"
ADMIN_USER="load-admin-$RUN_ID"
ADMIN_PASSWORD="$(secret)"

cd "$BACKEND_DIR"
echo "== migrate =="
"$BACKEND_PY" -m alembic upgrade head >/dev/null
"$BACKEND_PY" scripts/seed_test_account.py --username "$ADMIN_USER" --email "$ADMIN_USER@example.com" \
  --password "$ADMIN_PASSWORD" --passphrase "admin passphrase $(secret)" >/dev/null
"$BACKEND_PY" tests/e2e/live_server.py promote-admin --username "$ADMIN_USER" >/dev/null

echo "== start API on 127.0.0.1:$LOAD_PORT =="
"$BACKEND_PY" tests/e2e/live_server.py serve --port "$LOAD_PORT" >"$WORK_DIR/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do
  curl --silent --fail "http://127.0.0.1:$LOAD_PORT/health/ready" >/dev/null && break
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then cat "$WORK_DIR/server.log" >&2; exit 1; fi
  sleep 1
done

"$BACKEND_PY" scripts/register_recovery_key.py --api-base "$API" --username "$ADMIN_USER" \
  --password "$ADMIN_PASSWORD" --key-size 2048 --out "$WORK_DIR/recovery-private.pem" >/dev/null
echo "recovery key registered"

echo "== seed $LOAD_USERS load-test accounts =="
"$BACKEND_PY" scripts/seed_load_users.py --count "$LOAD_USERS" --prefix "load-$RUN_ID" --out "$ACCOUNTS"

cd "$LOADTEST_DIR"
run() { "$LOAD_PY" -m secureview_load --base-url "$API" --accounts "$ACCOUNTS" --out "$RESULTS" "$@"; }
if [ "${LOAD_QUICK:-0}" = "1" ]; then D=5; else D=15; fi
echo "== smoke =="
run smoke
echo "== simultaneous sign-ins =="
run logins --users "1,2,$LOAD_USERS" --rounds 2
echo "== steps (concurrent users) =="
run steps --users "1,2,$LOAD_USERS" --duration "$D" --size 256KiB --cooldown 2
echo "== parallel tasks per user =="
run parallel --users 2 --tasks 1,4 --duration "$D" --size 256KiB --cooldown 2
echo "== mixed load =="
run mixed --users "$LOAD_USERS" --duration "$((D * 2))" --size 256KiB --window 5 --seed 1
echo "== file types and sizes =="
run sizes --sizes 64KiB,1MiB,8MiB --types pdf,png,jpg,mp4,zip,exe
echo "== report =="
"$LOAD_PY" -m secureview_load.report "$RESULTS" --out "$RESULTS/REPORT.md"
echo "report: $RESULTS/REPORT.md"
