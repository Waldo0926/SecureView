"""Narrow attacker used only by the isolated SecureView tamper lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pymysql

LAB_ROOT = Path("/lab")
OBJECT_ROOT = LAB_ROOT / "storage" / "objects"
STATE_PATH = LAB_ROOT / "evidence" / "state.json"
MARKER_PATH = LAB_ROOT / ".secureview-tamper-lab"


def require_lab() -> dict[str, object]:
    database = os.environ.get("DB_NAME", "")
    if os.environ.get("APP_ENV") != "test" or "_test" not in database.lower():
        raise SystemExit("Refusing non-test environment or database")
    if not MARKER_PATH.is_file():
        raise SystemExit("Refusing storage without the SecureView tamper-lab marker")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def object_path(state: dict[str, object]) -> Path:
    root = OBJECT_ROOT.resolve(strict=False)
    path = (root / str(state["object_key"])).resolve(strict=False)
    if root not in path.parents:
        raise SystemExit("Refusing object path outside the lab volume")
    return path


def update_database(state: dict[str, object], *, digest: str, size: int) -> None:
    connection = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE files SET encrypted_sha256=%s, encrypted_size_bytes=%s, status='ACTIVE' "
                "WHERE file_uuid=%s",
                (digest, size, str(state["file_id"])),
            )
            if cursor.rowcount != 1:
                raise SystemExit("Disposable file row was not updated exactly once")
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("flip", "hide", "restore", "forge"))
    args = parser.parse_args()
    state = require_lab()
    path = object_path(state)
    parked = path.with_suffix(path.suffix + ".parked")

    if args.action == "flip":
        payload = bytearray(path.read_bytes())
        if not payload:
            raise SystemExit("Fixture ciphertext is unexpectedly empty")
        payload[0] ^= 0xFF
        path.write_bytes(payload)
    elif args.action == "hide":
        path.rename(parked)
    elif args.action == "restore":
        parked.rename(path)
    elif args.action == "forge":
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 0x01
        path.write_bytes(payload)
        update_database(state, digest=hashlib.sha256(payload).hexdigest(), size=len(payload))


if __name__ == "__main__":
    main()
