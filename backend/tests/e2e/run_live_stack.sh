#!/usr/bin/env bash
# Run every frontend live-backend suite against a disposable API + MySQL, with no skips.
#
# The frontend has three suites that talk to a real backend (crypto/mvp, crypto/upload,
# crypto/passphrase-reset) plus e2e/live-stack, and each one silently skips itself when
# its environment is missing. This script provides all of it -- migrated schema, seeded
# accounts, an admin, a registered recovery key, a running server -- then runs them and
# fails if any test was skipped. CI's `e2e-live` job runs exactly this; so can you:
#
#   DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=... DB_PASSWORD=... DB_NAME=fyp_e2e_test \
#     bash backend/tests/e2e/run_live_stack.sh
#
# Required (never printed): DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME. The database
# name must carry a `_test` segment; the server refuses anything else. Optional:
# E2E_PORT (8000), E2E_REPORT_DIR (where JUnit/coverage land; default ./e2e-reports),
# E2E_COVERAGE=1 to collect frontend coverage from the live run.
#
# E2E_BROWSER=1 also runs the Chromium smoke test (frontend/browser-tests) against the same
# stack once the Node suites pass; E2E_BROWSER=only runs it without them. It builds the
# frontend against this API, serves the build on 127.0.0.1:5173, and writes its JUnit and
# HTML report to E2E_BROWSER_REPORT_DIR (default ./e2e-browser-reports). Chromium must be
# installed first: `cd frontend && npx playwright install chromium`.
#
# E2E_BROWSER=capture runs neither: it takes the AC4a slide screenshots instead
# (frontend/browser-tests/capture/, docs/presentation/screenshots/) and writes them to
# E2E_CAPTURE_DIR. That run is the only one given the seeded admin's password, because the
# Admin Integrity and Security agent screens need it. Never used by CI.
#
# Every password and passphrase is generated here per run. Private keys, the mailbox and
# the uploaded objects live in a temporary directory that is removed on exit, and nothing
# in it is ever written to the report directory.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="$(cd "$BACKEND_DIR/../frontend" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_DIR/.venv/bin/python}"

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:?DB_NAME is required}"

START_DIR="$PWD"
E2E_PORT="${E2E_PORT:-8000}"
case "${E2E_BROWSER:-0}" in
  0) RUN_NODE_SUITES=1 RUN_BROWSER=0 ;;
  1) RUN_NODE_SUITES=1 RUN_BROWSER=1 ;;
  only) RUN_NODE_SUITES=0 RUN_BROWSER=1 ;;
  capture) RUN_NODE_SUITES=0 RUN_BROWSER=0
    : "${E2E_CAPTURE_DIR:?E2E_CAPTURE_DIR is required with E2E_BROWSER=capture}" ;;
  *) echo "E2E_BROWSER must be 0, 1, only or capture" >&2; exit 2 ;;
esac
REPORT_DIR="${E2E_REPORT_DIR:-$PWD/e2e-reports}"
mkdir -p "$REPORT_DIR"
REPORT_DIR="$(cd "$REPORT_DIR" && pwd)"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcs21-e2e.XXXXXX")"
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

export APP_ENV=test
export APP_DEBUG=false
export APP_DOCS_ENABLED=false
export SECRET_KEY="${SECRET_KEY:-$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export EMAIL_PROVIDER=console
export AUTH_REFRESH_MIN_INTERVAL_SECONDS=1
export ENCRYPTED_FILE_DIR="$WORK_DIR/objects"
export TEMP_FILE_DIR="$WORK_DIR/staging"
export E2E_MAILBOX_DIR="$WORK_DIR/mailbox"
export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
mkdir -p "$E2E_MAILBOX_DIR"

secret() {
  # Satisfies the password policy (upper, lower, digit, symbol) and is unique per run.
  "$PYTHON_BIN" -c 'import secrets; print("Aa1!" + secrets.token_urlsafe(24))'
}

RUN_ID="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(4))')"
ADMIN_USER="e2e-admin-$RUN_ID"
SENDER_USER="e2e-sender-$RUN_ID"
RECIPIENT_USER="e2e-recipient-$RUN_ID"
RESET_USER="e2e-reset-$RUN_ID"
ADMIN_PASSWORD="$(secret)"
SENDER_PASSWORD="$(secret)"
RECIPIENT_PASSWORD="$(secret)"
RESET_PASSWORD="$(secret)"
# Every account gets its own passphrase. With a shared one, the assertion that a recipient opens a
# shared file with their own key cannot be told apart from opening it with the sender's.
SENDER_PASSPHRASE="sender passphrase $(secret)"
RECIPIENT_PASSPHRASE="recipient passphrase $(secret)"
RESET_PASSPHRASE="reset passphrase $(secret)"
ADMIN_PASSPHRASE="admin passphrase $(secret)"
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  for value in "$SECRET_KEY" "$ADMIN_PASSWORD" "$SENDER_PASSWORD" "$RECIPIENT_PASSWORD" \
    "$RESET_PASSWORD" "$SENDER_PASSPHRASE" "$RECIPIENT_PASSPHRASE" "$RESET_PASSPHRASE" \
    "$ADMIN_PASSPHRASE"; do
    echo "::add-mask::$value"
  done
fi

cd "$BACKEND_DIR"
echo "== migrate =="
"$PYTHON_BIN" -m alembic upgrade head

seed() {
  "$PYTHON_BIN" scripts/seed_test_account.py --username "$1" --email "$1@example.com" \
    --password "$2" --passphrase "$3" "${@:4}" >/dev/null
  echo "seeded $1"
}
echo "== seed accounts =="
seed "$ADMIN_USER" "$ADMIN_PASSWORD" "$ADMIN_PASSPHRASE"
seed "$SENDER_USER" "$SENDER_PASSWORD" "$SENDER_PASSPHRASE"
seed "$RECIPIENT_USER" "$RECIPIENT_PASSWORD" "$RECIPIENT_PASSPHRASE"
seed "$RESET_USER" "$RESET_PASSWORD" "$RESET_PASSPHRASE" --private-key-out "$WORK_DIR/reset-key.pem"
"$PYTHON_BIN" tests/e2e/live_server.py promote-admin --username "$ADMIN_USER"

echo "== start API on 127.0.0.1:$E2E_PORT =="
"$PYTHON_BIN" tests/e2e/live_server.py serve --port "$E2E_PORT" >"$WORK_DIR/server.log" 2>&1 &
SERVER_PID=$!
API_ROOT="http://127.0.0.1:$E2E_PORT"
for _ in $(seq 1 60); do
  if curl --silent --fail "$API_ROOT/health/ready" >/dev/null; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "The API exited during startup:" >&2
    cat "$WORK_DIR/server.log" >&2
    exit 1
  fi
  sleep 1
done
curl --silent --fail "$API_ROOT/health/ready" >/dev/null

echo "== register a recovery key through the admin route =="
"$PYTHON_BIN" scripts/register_recovery_key.py --api-base "$API_ROOT/api/v1" \
  --username "$ADMIN_USER" --password "$ADMIN_PASSWORD" --key-size 2048 \
  --out "$WORK_DIR/recovery-private.pem" >/dev/null
echo "recovery key registered"

cd "$FRONTEND_DIR"
if [ "$RUN_NODE_SUITES" = "1" ]; then
  echo "== frontend live suites =="
  VITEST_ARGS=(run --no-file-parallelism --reporter=default --reporter=junit
    "--outputFile.junit=$REPORT_DIR/frontend-live-junit.xml")
  if [ "${E2E_COVERAGE:-0}" = "1" ]; then
    # Measured with every live suite running at 64.19% statements, 59.91% branches,
    # 65.18% functions, 65.31% lines; the floors sit a little below (issue #58).
    VITEST_ARGS+=(--coverage "--coverage.reportsDirectory=$REPORT_DIR/frontend-live-coverage"
      --coverage.thresholds.statements=62 --coverage.thresholds.branches=58
      --coverage.thresholds.functions=63 --coverage.thresholds.lines=63)
  fi
  status=0
  E2E_API_BASE="$API_ROOT/api/v1" \
  E2E_MAILBOX_DIR="$E2E_MAILBOX_DIR" \
  E2E_ADMIN_USERNAME="$ADMIN_USER" E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  E2E_REFRESH_MIN_INTERVAL_SECONDS="$AUTH_REFRESH_MIN_INTERVAL_SECONDS" \
  E2E_SENDER="$SENDER_USER" E2E_SENDER_PASSWORD="$SENDER_PASSWORD" \
  E2E_SENDER_PASSPHRASE="$SENDER_PASSPHRASE" \
  E2E_RECIPIENT="$RECIPIENT_USER" E2E_RECIPIENT_PASSWORD="$RECIPIENT_PASSWORD" \
  E2E_RECIPIENT_PASSPHRASE="$RECIPIENT_PASSPHRASE" \
  E2E_USERNAME="$SENDER_USER" E2E_PASSWORD="$SENDER_PASSWORD" \
  E2E_RESET_USER="$RESET_USER" E2E_RESET_PASSWORD="$RESET_PASSWORD" \
  E2E_RESET_PASSPHRASE="$RESET_PASSPHRASE" E2E_RESET_KEY_FILE="$WORK_DIR/reset-key.pem" \
    npx vitest "${VITEST_ARGS[@]}" || status=$?

  if [ "$status" -ne 0 ]; then
    echo "Frontend live suites failed; last API log lines (no bodies are logged):" >&2
    tail -n 40 "$WORK_DIR/server.log" >&2
    exit "$status"
  fi

  "$PYTHON_BIN" "$BACKEND_DIR/scripts/check_no_skips.py" "$REPORT_DIR/frontend-live-junit.xml"
fi

if [ "$RUN_BROWSER" = "1" ]; then
  echo "== browser smoke test (Chromium) =="
  BROWSER_REPORT_DIR="${E2E_BROWSER_REPORT_DIR:-$START_DIR/e2e-browser-reports}"
  mkdir -p "$BROWSER_REPORT_DIR"
  BROWSER_REPORT_DIR="$(cd "$BROWSER_REPORT_DIR" && pwd)"
  # The build the browser loads, pointed at this API. It lives in the work directory and is
  # removed with it, so it can never be mistaken for a deployable build.
  VITE_API_BASE_URL="$API_ROOT/api/v1" npx vite build --logLevel warn \
    --outDir "$WORK_DIR/web" --emptyOutDir
  # The browser suite registers its own throwaway accounts, so it receives only the
  # mailbox, never the seeded accounts' passwords or passphrases.
  status=0
  E2E_MAILBOX_DIR="$E2E_MAILBOX_DIR" E2E_WEB_DIR="$WORK_DIR/web" \
  E2E_BROWSER_REPORT_DIR="$BROWSER_REPORT_DIR" \
    npx playwright test || status=$?
  if [ "$status" -ne 0 ]; then
    echo "Browser smoke test failed; last API log lines (no bodies are logged):" >&2
    tail -n 40 "$WORK_DIR/server.log" >&2
    exit "$status"
  fi
  "$PYTHON_BIN" "$BACKEND_DIR/scripts/check_no_skips.py" "$BROWSER_REPORT_DIR/junit.xml"
fi

if [ "${E2E_BROWSER:-0}" = "capture" ]; then
  echo "== AC4a screenshots (Chromium) =="
  mkdir -p "$E2E_CAPTURE_DIR"
  CAPTURE_DIR="$(cd "$E2E_CAPTURE_DIR" && pwd)"
  VITE_API_BASE_URL="$API_ROOT/api/v1" npx vite build --logLevel warn \
    --outDir "$WORK_DIR/web" --emptyOutDir
  E2E_MAILBOX_DIR="$E2E_MAILBOX_DIR" E2E_WEB_DIR="$WORK_DIR/web" \
  E2E_BROWSER_REPORT_DIR="$WORK_DIR/capture-report" E2E_CAPTURE_DIR="$CAPTURE_DIR" \
  E2E_ADMIN_USERNAME="$ADMIN_USER" E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    npx playwright test --config playwright.capture.config.ts
fi
