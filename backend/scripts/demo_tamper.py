"""Tamper with one demo file's stored ciphertext for a live demonstration, and put it back.

Run on the server, from backend/, with the runtime environment loaded:

    PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py list    --owner demo-alice
    PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py flip    --owner demo-alice --file-id <uuid>
    PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py forge   --owner demo-alice --file-id <uuid>
    PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py restore --owner demo-alice --file-id <uuid>

flip    changes one byte of the stored object. The server's own SHA-256 check refuses the download.
forge   changes one byte and rewrites the recorded digest and size to match, as an attacker who
        controls storage and the database would. The digest check now agrees, but the digest the
        hash-chained audit log recorded at upload does not, so the download is still refused.
        (Past both server checks, the browser's AES-GCM tag is the last line; that layer is
        covered by frontend/src/crypto/download.test.ts rather than by editing the audit chain.)
restore puts the original bytes and the recorded digest, size and status back.
list    prints the owner's files with their ids, and marks any that are currently tampered.

Only files owned by an account whose name starts with ``demo-`` are touched, and only when the
named owner really owns the file. The original bytes and row values are kept under
``<ENCRYPTED_FILE_DIR>/../demo-tamper/`` until restore, and a second flip or forge is refused.
If the file was put back some other way (``scripts/restore_file.py``, the command the Admin
Integrity tab shows), the kept copy is recognised as stale: ``list`` no longer marks the file and
the next flip or forge goes ahead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.file import File
from app.models.user import User

DEMO_PREFIX = "demo-"


def _object_path(object_key: str) -> Path:
    root = settings.ENCRYPTED_FILE_DIR.resolve(strict=False)
    path = (root / object_key).resolve(strict=False)
    if root not in path.parents:
        raise SystemExit("Refusing an object path outside the encrypted storage root")
    return path


def _backup_dir() -> Path:
    directory = settings.ENCRYPTED_FILE_DIR.resolve(strict=False).parent / "demo-tamper"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def _flip_one_byte(path: Path) -> bytes:
    """Change the middle byte in place, keeping the file's owner and mode."""
    size = path.stat().st_size
    if size == 0:
        raise SystemExit("The stored object is empty")
    offset = size // 2
    with path.open("r+b") as handle:
        handle.seek(offset)
        original = handle.read(1)
        handle.seek(offset)
        handle.write(bytes([original[0] ^ 0x01]))
        handle.flush()
        os.fsync(handle.fileno())
    return path.read_bytes()


def _already_put_back(path: Path, saved_bytes: Path, saved_row: Path, recorded_sha256: str) -> bool:
    """True when the stored object and its digest are the kept original again.

    That happens when the administrator restored the file from backup with restore_file.py
    instead of `restore` here. The kept copy then describes nothing and must not block the next
    rehearsal's flip.
    """
    if not saved_bytes.exists() or not saved_row.exists() or not path.exists():
        return False
    original = json.loads(saved_row.read_text())
    return (
        recorded_sha256 == original["encrypted_sha256"]
        and path.read_bytes() == saved_bytes.read_bytes()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("flip", "forge", "restore", "list"))
    parser.add_argument("--owner", required=True, help="the demo account that owns the file")
    parser.add_argument("--file-id", type=UUID, help="required for flip, forge and restore")
    args = parser.parse_args()

    if not args.owner.startswith(DEMO_PREFIX):
        raise SystemExit(f"Refusing: only accounts named {DEMO_PREFIX}* are used for the demo")
    if args.action != "list" and args.file_id is None:
        parser.error(f"{args.action} needs --file-id")

    with SessionLocal() as db:
        if args.action == "list":
            files = db.execute(
                select(
                    File.file_uuid,
                    File.original_filename,
                    File.status,
                    File.storage_object_key,
                    File.encrypted_sha256,
                )
                .join(User, User.id == File.owner_id)
                .where(User.username == args.owner, File.deleted_at.is_(None))
                .order_by(File.created_at.desc())
            ).all()
            if not files:
                print(f"{args.owner} has no files")
            for file_uuid, name, status, object_key, recorded_sha256 in files:
                saved_bytes = _backup_dir() / f"{file_uuid}.orig"
                tampered = saved_bytes.exists() and not _already_put_back(
                    _object_path(object_key),
                    saved_bytes,
                    _backup_dir() / f"{file_uuid}.json",
                    recorded_sha256,
                )
                print(f"{file_uuid}  {status:<8}  {'TAMPERED  ' if tampered else ''}{name}")
            return 0

        row = db.execute(
            select(File, User.username)
            .join(User, User.id == File.owner_id)
            .where(File.file_uuid == str(args.file_id))
        ).one_or_none()
        if row is None:
            raise SystemExit("No such file")
        record, owner = row
        if owner != args.owner:
            raise SystemExit(f"Refusing: that file belongs to {owner}, not {args.owner}")

        path = _object_path(record.storage_object_key)
        saved_bytes = _backup_dir() / f"{args.file_id}.orig"
        saved_row = _backup_dir() / f"{args.file_id}.json"

        if args.action in ("flip", "forge"):
            if _already_put_back(path, saved_bytes, saved_row, record.encrypted_sha256):
                saved_bytes.unlink()
                saved_row.unlink()
                print("The file had already been restored from backup; starting afresh.")
            if saved_bytes.exists():
                raise SystemExit("Already tampered; run restore first")
            saved_bytes.write_bytes(path.read_bytes())
            saved_bytes.chmod(0o600)
            saved_row.write_text(
                json.dumps(
                    {
                        "encrypted_sha256": record.encrypted_sha256,
                        "encrypted_size_bytes": record.encrypted_size_bytes,
                        "status": record.status,
                    }
                )
            )
            saved_row.chmod(0o600)
            tampered = _flip_one_byte(path)
            if args.action == "forge":
                record.encrypted_sha256 = hashlib.sha256(tampered).hexdigest()
                record.encrypted_size_bytes = len(tampered)
                db.commit()
                print("Forged: one byte changed AND the recorded digest rewritten to match.")
                print("The digest check agrees now; the audit-chain anchor must still refuse it.")
            else:
                print("Flipped one byte of the stored ciphertext.")
                print("The server's SHA-256 check will refuse the download.")
            return 0

        if not saved_bytes.exists():
            raise SystemExit("Nothing to restore for that file")
        original = json.loads(saved_row.read_text())
        with path.open("r+b") as handle:
            handle.write(saved_bytes.read_bytes())
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        record.encrypted_sha256 = original["encrypted_sha256"]
        record.encrypted_size_bytes = original["encrypted_size_bytes"]
        record.status = original["status"]
        db.commit()
        saved_bytes.unlink()
        saved_row.unlink()
        print("Restored the original bytes, digest, size and status.")
        print("Click the file's status badge in My Files once, so its newest check is VALID again.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
