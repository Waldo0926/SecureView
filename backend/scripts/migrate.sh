#!/usr/bin/env bash
# Serialize "alembic upgrade head" behind a MySQL named lock.
#
# MySQL gives Alembic no migration lock of its own: two deployers who run
# "alembic upgrade head" at the same time can both read the same starting
# revision and race to apply the same DDL, and the loser fails loudly (or, on
# an unlucky interleaving, applies half of it). GET_LOCK()/RELEASE_LOCK() are
# session-scoped and connection-independent, so wrapping the upgrade in them
# makes a second, concurrent invocation wait for the first to finish instead
# of racing it, then simply no-op (there is nothing left to apply) once it
# gets its turn.
#
# Usage:
#   backend/scripts/migrate.sh upgrade head
#   backend/scripts/migrate.sh current
#   backend/scripts/migrate.sh check
#
# Reads the same DB_* environment variables as the application (see
# app/core/config.py). Never echoes DB_PASSWORD.
set -euo pipefail

LOCK_NAME="${MIGRATE_LOCK_NAME:-fyp_secure_file_platform_migrate}"
LOCK_TIMEOUT_SECONDS="${MIGRATE_LOCK_TIMEOUT_SECONDS:-60}"

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND_DIR"

if [ "$#" -eq 0 ]; then
  echo "usage: migrate.sh <alembic-subcommand> [args...]" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python}"

exec "$PYTHON_BIN" - "$LOCK_NAME" "$LOCK_TIMEOUT_SECONDS" "$@" <<'PYEOF'
from __future__ import annotations

import subprocess
import sys

from sqlalchemy import create_engine, text

from app.core.config import settings

lock_name = sys.argv[1]
lock_timeout_seconds = int(sys.argv[2])
alembic_args = sys.argv[3:]

engine = create_engine(settings.DATABASE_URL, connect_args=settings.DATABASE_CONNECT_ARGS)

with engine.connect() as connection:
    # Try once without waiting so a deployer can see (and the release gate can
    # assert) that it queued behind another migration rather than racing it.
    acquired = connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
    if acquired != 1:
        print(
            f"migrate.sh: lock '{lock_name}' is held by another migration; "
            f"waiting up to {lock_timeout_seconds}s",
            file=sys.stderr,
            flush=True,
        )
        acquired = connection.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": lock_name, "timeout": lock_timeout_seconds},
        ).scalar()
    if acquired != 1:
        print(
            f"migrate.sh: could not acquire lock '{lock_name}' within "
            f"{lock_timeout_seconds}s; another migration is likely stuck",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = subprocess.run([sys.executable, "-m", "alembic", *alembic_args])
    finally:
        connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})

sys.exit(result.returncode)
PYEOF
