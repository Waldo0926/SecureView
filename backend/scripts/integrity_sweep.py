"""Verify the stored ciphertext objects against their recorded SHA-256, on a schedule.

Until this existed an object was only looked at when its owner downloaded it or clicked the
integrity check, so tampering with a file nobody opened could go unseen indefinitely. This
reads every stored object (least recently checked first), compares it with the digest the
system recorded and the one the audit chain recorded at upload, and writes the findings to
`integrity_checks` and the audit log. It reads ciphertext only, needs no key, and never
changes an object: putting a damaged one back is `restore_file.py`, a deliberate human step.

Exit status is 0 when everything checked was intact, and 3 when any object was modified,
missing or unreadable, so the systemd unit fails and its OnFailure= alert fires. It stops
at `--budget-seconds` and the next run continues with whatever was checked longest ago.

Run from `backend/` with the deployment environment loaded:

    .venv/bin/python scripts/integrity_sweep.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domain.auth import RequestContext
from app.services.audit_log_service import AuditLogService
from app.services.file_storage_service import FileStorageService
from app.services.integrity_service import IntegrityService

DAMAGE_EXIT_STATUS = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--limit", type=int, default=500, help="most files to check in one run")
    parser.add_argument("--budget-seconds", type=float, default=1500.0)
    args = parser.parse_args(argv)

    settings = get_settings()
    with SessionLocal() as db:
        audit = AuditLogService(db)
        service = IntegrityService(
            db=db,
            settings=settings,
            storage=FileStorageService(settings=settings),
            audit_service=audit,
        )
        summary = service.sweep(
            actor_user_id=None,
            context=RequestContext(user_agent="scripts/integrity_sweep.py"),
            limit=args.limit,
            budget_seconds=args.budget_seconds,
        )
    print(
        json.dumps(
            {
                "scanned": summary.scanned,
                "valid": summary.valid,
                "modified": summary.modified,
                "missing": summary.missing,
                "error": summary.error,
                "candidates": summary.candidates,
                "stopped_early": summary.stopped_early,
                "damaged_file_ids": summary.damaged_file_ids,
            }
        )
    )
    if summary.damaged:
        print(
            f"integrity_sweep: {summary.damaged} damaged object(s); see docs/BACKUP_AND_RECOVERY.md "
            "section 9 to restore one",
            file=sys.stderr,
        )
        return DAMAGE_EXIT_STATUS
    return 0


if __name__ == "__main__":
    sys.exit(main())
