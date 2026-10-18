#!/usr/bin/env python3
"""Publish and independently verify an external anchor for the audit hash chain.

The checkpoint contains only the audit-chain head, schema revision, release SHA and UTC
timestamps. It contains no audit rows, users, file names, request bodies, tokens, keys, or
credentials. A root-only random HMAC key authenticates the canonical payload; the application
process does not receive that key.

Staging publishes to S3-compatible object storage. A local destination exists only for tests
and drills and requires --allow-local-dest so it cannot be mistaken for an external anchor.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymysql

FORMAT_VERSION = 1
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CheckpointError(Exception):
    pass


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    ssl_ca: str | None


def _first_env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def db_config_from_env() -> DbConfig:
    user = _first_env("CHECKPOINT_DB_USER", "BACKUP_DB_USER", "DB_USER")
    password = _first_env(
        "CHECKPOINT_DB_PASSWORD",
        "BACKUP_DB_PASSWORD",
        "DB_PASSWORD",
    )
    if not user or not password:
        raise CheckpointError(
            "a read-only database user/password must be supplied via CHECKPOINT_DB_*, "
            "BACKUP_DB_*, or DB_*"
        )

    port_value = _first_env(
        "CHECKPOINT_DB_PORT",
        "BACKUP_DB_PORT",
        "DB_PORT",
        default="3306",
    )
    try:
        port = int(port_value or "3306")
    except ValueError as exc:
        raise CheckpointError("database port is invalid") from exc

    return DbConfig(
        host=(
            _first_env(
                "CHECKPOINT_DB_HOST",
                "BACKUP_DB_HOST",
                "DB_HOST",
                default="127.0.0.1",
            )
            or "127.0.0.1"
        ),
        port=port,
        database=(
            _first_env(
                "CHECKPOINT_DB_NAME",
                "BACKUP_DB_NAME",
                "DB_NAME",
                default="fyp_secure_file_platform",
            )
            or "fyp_secure_file_platform"
        ),
        user=user,
        password=password,
        ssl_ca=_first_env(
            "CHECKPOINT_DB_SSL_CA",
            "BACKUP_DB_SSL_CA",
            "DB_SSL_CA",
        ),
    )


def connect(config: DbConfig):
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        ssl_ca=config.ssl_ca,
        ssl_verify_cert=bool(config.ssl_ca),
        ssl_verify_identity=False,
        connect_timeout=10,
    )


def _api_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def read_chain_head(config: DbConfig) -> dict[str, Any]:
    connection = connect(config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT last_log_id, current_hash, schema_revision, updated_at "
                "FROM audit_chain_heads WHERE id = 1"
            )
            row = cursor.fetchone()
    finally:
        connection.close()

    if row is None:
        raise CheckpointError("audit chain head row is missing")

    last_log_id, current_hash, schema_revision, updated_at = row
    current_hash = str(current_hash)
    if not _HASH_RE.fullmatch(current_hash):
        raise CheckpointError("audit chain head hash is malformed")
    if not isinstance(updated_at, datetime):
        raise CheckpointError("audit chain head timestamp is malformed")

    return {
        "last_log_id": int(last_log_id) if last_log_id is not None else None,
        "current_hash": current_hash,
        "schema_revision": str(schema_revision),
        "updated_at": _api_utc(updated_at),
    }


def read_release_sha(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip().lower()
    except OSError as exc:
        raise CheckpointError("release identity file is unreadable") from exc
    if not _SHA_RE.fullmatch(value):
        raise CheckpointError("release identity is not a full Git commit SHA")
    return value


def load_hmac_key(path: Path) -> bytes:
    try:
        raw = path.read_bytes().strip()
    except OSError as exc:
        raise CheckpointError("HMAC key file is unreadable") from exc

    key = bytes.fromhex(raw.decode("ascii")) if re.fullmatch(rb"[0-9A-Fa-f]{64}", raw) else raw
    if len(key) < 32:
        raise CheckpointError("HMAC key must contain at least 256 bits of random material")
    return key


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_payload(payload), hashlib.sha256).hexdigest()


def build_document(
    *,
    chain_head: dict[str, Any],
    release_sha: str,
    key: bytes,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    now = (created_at or datetime.now(UTC)).astimezone(UTC)
    payload = {
        "format_version": FORMAT_VERSION,
        "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "release_sha": release_sha,
        "audit_chain": chain_head,
    }
    return {
        "payload": payload,
        "authentication": {
            "algorithm": "HMAC-SHA256",
            "value": sign_payload(payload, key),
        },
    }


def verify_document(document: dict[str, Any], key: bytes) -> dict[str, Any]:
    payload = document.get("payload")
    authentication = document.get("authentication")
    if not isinstance(payload, dict) or not isinstance(authentication, dict):
        raise CheckpointError("checkpoint document shape is invalid")
    if payload.get("format_version") != FORMAT_VERSION:
        raise CheckpointError("checkpoint format version is unsupported")
    if authentication.get("algorithm") != "HMAC-SHA256":
        raise CheckpointError("checkpoint authentication algorithm is unsupported")

    supplied = authentication.get("value")
    if not isinstance(supplied, str) or not _HASH_RE.fullmatch(supplied):
        raise CheckpointError("checkpoint HMAC is malformed")
    expected = sign_payload(payload, key)
    if not hmac.compare_digest(supplied, expected):
        raise CheckpointError("checkpoint HMAC verification failed")

    chain = payload.get("audit_chain")
    if not isinstance(chain, dict) or not _HASH_RE.fullmatch(str(chain.get("current_hash", ""))):
        raise CheckpointError("checkpoint audit-chain payload is malformed")
    return payload


def serialize_document(document: dict[str, Any]) -> bytes:
    rendered = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"{rendered}\n".encode()


def checkpoint_name(payload: dict[str, Any]) -> str:
    created = str(payload["created_at"]).replace("-", "").replace(":", "")
    last_id = payload["audit_chain"].get("last_log_id")
    suffix = "genesis" if last_id is None else str(last_id)
    return f"audit-checkpoint-{created}-{suffix}.json"


def _ship_s3(path: Path, destination: str) -> str:
    aws = shutil.which("aws")
    if aws is None:
        raise CheckpointError("S3 destination requires the aws CLI")

    target = f"{destination.rstrip('/')}/{path.name}"
    command = [aws, "s3", "cp", "--only-show-errors", str(path), target]
    endpoint = _first_env(
        "AUDIT_CHECKPOINT_S3_ENDPOINT_URL",
        "BACKUP_S3_ENDPOINT_URL",
    )
    if endpoint:
        command += ["--endpoint-url", endpoint]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise CheckpointError("external checkpoint upload failed") from exc
    return target


def ship(path: Path, destination: str, *, allow_local: bool) -> str:
    if destination.startswith("s3://"):
        return _ship_s3(path, destination)
    if not allow_local:
        raise CheckpointError("checkpoint destination must be external (s3://) on staging")

    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / path.name
    if target.exists():
        raise CheckpointError("checkpoint target already exists")
    target.write_bytes(path.read_bytes())
    target.chmod(0o600)
    return str(target)


def write_stamp(
    path: Path,
    *,
    payload: dict[str, Any],
    checkpoint_sha256: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    stamp = {
        "created_at": payload["created_at"],
        "last_log_id": payload["audit_chain"].get("last_log_id"),
        "checkpoint_sha256": checkpoint_sha256,
    }
    fd, temporary = tempfile.mkstemp(prefix=".audit-checkpoint-", dir=path.parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stamp, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def read_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError("checkpoint document is unreadable") from exc
    if not isinstance(value, dict):
        raise CheckpointError("checkpoint document is not a JSON object")
    return value


def verify_live_anchor(payload: dict[str, Any], config: DbConfig) -> None:
    chain = payload["audit_chain"]
    checkpoint_id = chain.get("last_log_id")
    checkpoint_hash = str(chain["current_hash"])
    connection = connect(config)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT last_log_id FROM audit_chain_heads WHERE id = 1")
            head = cursor.fetchone()
            if head is None:
                raise CheckpointError("live audit chain head row is missing")
            live_last_id = head[0]
            if checkpoint_id is None:
                if live_last_id is not None:
                    raise CheckpointError("live chain has advanced beyond the genesis checkpoint")
                return
            cursor.execute(
                "SELECT current_hash FROM audit_logs WHERE id = %s",
                (checkpoint_id,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()

    if live_last_id is None or int(live_last_id) < int(checkpoint_id):
        raise CheckpointError("live audit chain is behind the checkpoint")
    if row is None or not hmac.compare_digest(str(row[0]), checkpoint_hash):
        raise CheckpointError("live audit chain no longer contains the checkpoint anchor")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--key-file", type=Path, required=True)
    create.add_argument("--dest", required=True)
    create.add_argument(
        "--release-file",
        type=Path,
        default=Path("/opt/mcs21/current/.mcs21-release"),
    )
    create.add_argument("--stamp-file", type=Path)
    create.add_argument("--allow-local-dest", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("checkpoint", type=Path)
    verify.add_argument("--key-file", type=Path, required=True)

    verify_live = subparsers.add_parser("verify-live")
    verify_live.add_argument("checkpoint", type=Path)
    verify_live.add_argument("--key-file", type=Path, required=True)

    return parser.parse_args(argv)


def create_checkpoint(args: argparse.Namespace) -> int:
    key = load_hmac_key(args.key_file)
    payload_head = read_chain_head(db_config_from_env())
    release_sha = read_release_sha(args.release_file)
    document = build_document(
        chain_head=payload_head,
        release_sha=release_sha,
        key=key,
    )
    payload = document["payload"]
    data = serialize_document(document)
    digest = hashlib.sha256(data).hexdigest()

    with tempfile.TemporaryDirectory(prefix="mcs21-audit-checkpoint.") as temp:
        path = Path(temp) / checkpoint_name(payload)
        path.write_bytes(data)
        path.chmod(0o600)
        destination = ship(
            path,
            args.dest,
            allow_local=args.allow_local_dest,
        )

    if args.stamp_file is not None:
        write_stamp(
            args.stamp_file,
            payload=payload,
            checkpoint_sha256=digest,
        )

    print(
        json.dumps(
            {
                "event": "audit_checkpoint.published",
                "last_log_id": payload["audit_chain"].get("last_log_id"),
                "checkpoint_sha256": digest,
                "destination_type": ("s3" if args.dest.startswith("s3://") else "local"),
                "object": Path(destination).name,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def verify_checkpoint(args: argparse.Namespace, *, compare_live: bool) -> int:
    key = load_hmac_key(args.key_file)
    payload = verify_document(read_document(args.checkpoint), key)
    if compare_live:
        verify_live_anchor(payload, db_config_from_env())
    print(
        json.dumps(
            {
                "event": "audit_checkpoint.verified",
                "last_log_id": payload["audit_chain"].get("last_log_id"),
                "release_sha": payload["release_sha"],
                "live_anchor_checked": compare_live,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "create":
            return create_checkpoint(args)
        if args.command == "verify":
            return verify_checkpoint(args, compare_live=False)
        if args.command == "verify-live":
            return verify_checkpoint(args, compare_live=True)
        raise CheckpointError("unknown command")  # pragma: no cover
    except CheckpointError as exc:
        print(
            json.dumps(
                {
                    "event": "audit_checkpoint.failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # do not echo arbitrary driver/subprocess exception text
        print(
            json.dumps(
                {
                    "event": "audit_checkpoint.failed",
                    "error_type": type(exc).__name__,
                    "error": "unexpected checkpoint failure",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
