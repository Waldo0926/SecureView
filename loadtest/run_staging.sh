#!/usr/bin/env bash
# Run the staging load test through the public URL, the same path a real user takes:
# HTTPS, nginx and its per-address limits, then the API.
#
#   LOAD_ACCOUNTS=loadtest-accounts.json bash loadtest/run_staging.sh
#   LOAD_ACCOUNTS=loadtest-accounts.json LOAD_LARGE_FILES=1 bash loadtest/run_staging.sh
#
# By default it runs the user ladder, parallel tasks, sign-ins, a 5-minute mixed load and the
# overload and recovery steps. The file size matrix (six types, 1 MiB to 500 MiB, about 5 GiB
# each way) only runs with LOAD_LARGE_FILES=1, because on a home connection it takes well over an
# hour and fills the uplink. LOAD_ONLY_LARGE=1 runs the matrix alone.
#
# Everything goes out from one address, so nginx's 30 requests per second per address can answer
# 429. That is the limiter working, not the server failing; the report counts 429 separately.
# Do not switch the limits off for a run.
#
# Optional: LOAD_BASE_URL (default https://secureview.tech/api/v1), LOAD_RESULTS (default
# ./results).
set -euo pipefail

LOADTEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD_PY="${LOAD_PY:-$LOADTEST_DIR/.venv/bin/python}"
BASE="${LOAD_BASE_URL:-https://secureview.tech/api/v1}"
: "${LOAD_ACCOUNTS:?LOAD_ACCOUNTS must point at the file seed_load_users.py wrote}"
LOAD_ACCOUNTS="$(cd "$(dirname "$LOAD_ACCOUNTS")" && pwd)/$(basename "$LOAD_ACCOUNTS")"
RESULTS="${LOAD_RESULTS:-$PWD/results}"
mkdir -p "$RESULTS"
RESULTS="$(cd "$RESULTS" && pwd)"

run() {
  echo "== $* ($(date -u +%H:%M:%SZ)) =="
  # A failed scenario is recorded in its summary; keep going so one bad step does not hide the rest.
  (cd "$LOADTEST_DIR" && "$LOAD_PY" -m secureview_load --base-url "$BASE" --accounts "$LOAD_ACCOUNTS" \
    --confirm-remote --out "$RESULTS" "$@") || echo "scenario exited non-zero: $*"
}

if [ "${LOAD_ONLY_LARGE:-0}" != "1" ]; then
  run smoke --size 1MiB
  run steps --users 1,5,10,20,50,100 --duration 60 --size 1MiB
  run parallel --users 5 --tasks 1,2,5,10 --duration 60
  run logins --users 1,2,4,8,16 --rounds 3
  run mixed --users 5 --duration 300
  run steps --users 5,50,100,5 --duration 60 --size 1MiB
fi

if [ "${LOAD_LARGE_FILES:-0}" = "1" ] || [ "${LOAD_ONLY_LARGE:-0}" = "1" ]; then
  run sizes --sizes 1MiB,10MiB,50MiB,100MiB,200MiB,500MiB --types pdf,png,jpg,mp4,zip,exe
else
  echo "== sizes skipped: set LOAD_LARGE_FILES=1 to upload the 1 MiB to 500 MiB matrix =="
fi
echo "== done ($(date -u +%H:%M:%SZ)) =="
