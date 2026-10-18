#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"
BASE="http://127.0.0.1:18000/api/v1"
ACC="loadtest-accounts.json"
OUT="results"

echo "=== steps (concurrent users 1..100) ==="
.venv/bin/python -m secureview_load --base-url "$BASE" --accounts "$ACC" --confirm-remote --out "$OUT" \
  steps --users 1,5,10,20,50,100 --duration 60 --size 1MiB

echo "=== sizes (file size x type matrix) ==="
.venv/bin/python -m secureview_load --base-url "$BASE" --accounts "$ACC" --confirm-remote --out "$OUT" \
  sizes --sizes 1MiB,10MiB,50MiB,100MiB,200MiB,500MiB --types pdf,png,jpg,mp4,zip,exe

echo "=== parallel (tasks per user) ==="
.venv/bin/python -m secureview_load --base-url "$BASE" --accounts "$ACC" --confirm-remote --out "$OUT" \
  parallel --users 5 --tasks 1,2,5,10 --duration 60

echo "=== logins (simultaneous sign-ins) ==="
.venv/bin/python -m secureview_load --base-url "$BASE" --accounts "$ACC" --confirm-remote --out "$OUT" \
  logins --users 1,2,4,8,16 --rounds 3

echo "=== PHASE1 DONE ==="
