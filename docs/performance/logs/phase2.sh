#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"
BASE="http://127.0.0.1:18000/api/v1"
ACC="loadtest-accounts.json"
OUT="results"
run() { .venv/bin/python -m secureview_load --base-url "$BASE" --accounts "$ACC" --confirm-remote --out "$OUT" "$@"; }

while kill -0 88768 2>/dev/null; do sleep 10; done
echo "=== phase1 finished at $(date) ==="

# Re-open the tunnel if it dropped during phase 1.
if ! curl -sf -o /dev/null http://127.0.0.1:18000/health/live; then
  pkill -f "ssh -f -N -L 18000" ; sleep 1
  ssh -f -N -L 18000:127.0.0.1:8000 <server>; sleep 2
fi

echo "=== mixed 5 users 300s ($(date)) ==="
run mixed --users 5 --duration 300

for d in 900 1800 3600; do
  echo "=== soak mixed 5 users ${d}s ($(date)) ==="
  run mixed --users 5 --duration "$d" --window 60
done

echo "=== overload and recovery 5,50,100,5 ($(date)) ==="
run steps --users 5,50,100,5 --duration 60 --size 1MiB

echo "=== PHASE2 DONE $(date) ==="
