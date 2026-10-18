"""Exercise SecureView integrity decisions against a disposable lab database.

This is deliberately not a production repair tool.  It refuses to run unless the
application is in test mode, the database name contains ``_test``, and a lab marker is
present beside the isolated object store.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from tests.integration._concurrency_support import (
    active_recovery_key,
    file_service,
    register_real_user,
    session_scope,
    upload_file,
)
from tests.integration.test_file_lifecycle_mysql import _file_content_aad

from app.core.config import settings
from app.core.database import engine
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import IntegrityVerificationError
from app.models.file import File

LAB_ROOT = Path("/lab")
STORAGE_ROOT = LAB_ROOT / "storage"
EVIDENCE_ROOT = LAB_ROOT / "evidence"
PRIVATE_ROOT = LAB_ROOT / "private"
STATE_PATH = EVIDENCE_ROOT / "state.json"
REPORT_PATH = EVIDENCE_ROOT / "report.json"
PRIVATE_PATH = PRIVATE_ROOT / "crypto.json"
MARKER_PATH = LAB_ROOT / ".secureview-tamper-lab"


def require_lab() -> None:
    if settings.APP_ENV != "test":
        raise SystemExit("Refusing to run outside APP_ENV=test")
    if "_test" not in settings.DB_NAME.lower():
        raise SystemExit("Refusing a database whose name does not contain _test")
    if not MARKER_PATH.is_file():
        raise SystemExit("Refusing storage without the SecureView tamper-lab marker")
    if STORAGE_ROOT.resolve(strict=False) != Path(settings.ENCRYPTED_FILE_DIR).parent.resolve(
        strict=False
    ):
        raise SystemExit("Refusing an encrypted-object directory outside /lab/storage")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def append_result(name: str, **values: object) -> None:
    report = read_json(REPORT_PATH)
    steps = report.setdefault("steps", [])
    if not isinstance(steps, list):
        raise SystemExit("Invalid lab report structure")
    steps.append({"name": name, **values})
    write_json(REPORT_PATH, report)


def actor_from_state(state: dict[str, object]) -> ActorContext:
    return ActorContext(
        user_id=int(state["user_id"]),
        user_public_id=UUID(str(state["user_uuid"])),
        session_id=0,
        session_public_id=uuid4(),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="0" * 64,
    )


def seed() -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    owner = register_real_user(engine, prefix="tamper-drill")
    with active_recovery_key(engine) as recovery:
        uploaded = upload_file(engine, STORAGE_ROOT, owner, recovery)

    with session_scope(engine) as session:
        row = session.scalar(select(File).where(File.file_uuid == str(uploaded.file_id)))
        if row is None:
            raise SystemExit("Seeded file row disappeared")
        object_path = Path(settings.ENCRYPTED_FILE_DIR) / row.storage_object_key
        original = object_path.read_bytes()
        state = {
            "file_id": str(uploaded.file_id),
            "user_id": owner.user_id,
            "user_uuid": str(owner.user_uuid),
            "object_key": row.storage_object_key,
            "original_sha256": row.encrypted_sha256,
            "original_size": row.encrypted_size_bytes,
        }
        private = {
            "dek": base64.b64encode(uploaded.dek).decode("ascii"),
            "nonce": base64.b64encode(row.iv).decode("ascii"),
            "auth_tag": base64.b64encode(row.auth_tag).decode("ascii"),
        }
        (PRIVATE_ROOT / "original.ciphertext").write_bytes(original)
        write_json(PRIVATE_PATH, private)
        write_json(STATE_PATH, state)
        write_json(
            REPORT_PATH,
            {
                "schema_version": 1,
                "database": "disposable_mysql_8_4_test",
                "fixture": "synthetic_client_encrypted_object",
                "steps": [],
            },
        )


def inspect(expected_result: str, expected_file_status: str, *, download: str) -> None:
    state = read_json(STATE_PATH)
    actor = actor_from_state(state)
    file_id = UUID(str(state["file_id"]))
    with session_scope(engine) as session:
        service = file_service(session, STORAGE_ROOT)
        result = service.integrity_check(
            actor=actor,
            file_id=file_id,
            context=RequestContext(user_agent="vps-tamper-drill"),
        )
        row = session.scalar(select(File).where(File.file_uuid == str(file_id)))
        if row is None:
            raise SystemExit("Lab file row disappeared")
        if result.status != expected_result or row.status != expected_file_status:
            raise SystemExit(
                f"Unexpected integrity state: result={result.status}, file_status={row.status}"
            )

        download_outcome = "not_checked"
        if download == "allowed":
            downloaded = service.download(
                actor=actor,
                file_id=file_id,
                context=RequestContext(user_agent="vps-tamper-drill"),
            )
            downloaded.verified_ciphertext.stream.close()
            download_outcome = "allowed"
        elif download == "refused":
            try:
                service.download(
                    actor=actor,
                    file_id=file_id,
                    context=RequestContext(user_agent="vps-tamper-drill"),
                )
            except IntegrityVerificationError:
                download_outcome = "refused"
            else:
                raise SystemExit("Tampered ciphertext download was unexpectedly allowed")

    append_result(
        expected_result.lower(),
        integrity_result=result.status,
        durable_file_status=row.status,
        download=download_outcome,
    )


def prove_client_authentication_failure() -> None:
    state = read_json(STATE_PATH)
    private = read_json(PRIVATE_PATH)
    object_path = Path(settings.ENCRYPTED_FILE_DIR) / str(state["object_key"])
    ciphertext = object_path.read_bytes()
    original = (PRIVATE_ROOT / "original.ciphertext").read_bytes()
    key = AESGCM(base64.b64decode(str(private["dek"]), validate=True))
    nonce = base64.b64decode(str(private["nonce"]), validate=True)
    auth_tag = base64.b64decode(str(private["auth_tag"]), validate=True)
    with session_scope(engine) as session:
        row = session.scalar(select(File).where(File.file_uuid == str(state["file_id"])))
        if row is None:
            raise SystemExit("Lab file row disappeared")
        aad = _file_content_aad(
            file_id=UUID(row.file_uuid),
            filename=row.original_filename,
            plaintext_size=row.file_size_bytes,
            mime=row.mime_type or "application/octet-stream",
        )
    # Prove the fixture/key/AAD combination is sound before treating InvalidTag as evidence.
    key.decrypt(nonce, original + auth_tag, aad)
    rejected = False
    try:
        key.decrypt(nonce, ciphertext + auth_tag, aad)
    except InvalidTag:
        rejected = True
    if not rejected:
        raise SystemExit("Authenticated decryption unexpectedly accepted forged ciphertext")
    append_result(
        "database_and_object_compromise",
        server_sha256_comparison="matches_the_rewritten_row",
        server_audit_anchor_comparison="detected",
        server_download="refused",
        client_authenticated_decryption="rejected_invalid_tag",
    )


def restore_baseline() -> None:
    state = read_json(STATE_PATH)
    original = (PRIVATE_ROOT / "original.ciphertext").read_bytes()
    object_path = Path(settings.ENCRYPTED_FILE_DIR) / str(state["object_key"])
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(original)
    with session_scope(engine) as session:
        row = session.scalar(select(File).where(File.file_uuid == str(state["file_id"])))
        if row is None:
            raise SystemExit("Lab file row disappeared")
        row.encrypted_sha256 = hashlib.sha256(original).hexdigest()
        row.encrypted_size_bytes = len(original)
        session.commit()


def finish() -> None:
    report = read_json(REPORT_PATH)
    report["outcome"] = "passed"
    report["production_data_touched"] = False
    report["security_boundary"] = (
        "SHA-256 detects object-only tampering, and the digest the upload recorded in the audit "
        "hash chain detects rewriting the object and its database digest together; AEAD "
        "authentication in the client remains required if the audit log is compromised as well."
    )
    write_json(REPORT_PATH, report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--expect-result", required=True)
    inspect_parser.add_argument("--expect-file-status", required=True)
    inspect_parser.add_argument(
        "--download", choices=("allowed", "refused", "skip"), default="skip"
    )
    sub.add_parser("prove-client-auth")
    sub.add_parser("restore-baseline")
    sub.add_parser("finish")
    return parser.parse_args()


def main() -> None:
    require_lab()
    args = parse_args()
    if args.command == "seed":
        seed()
    elif args.command == "inspect":
        inspect(args.expect_result, args.expect_file_status, download=args.download)
    elif args.command == "prove-client-auth":
        prove_client_authentication_failure()
    elif args.command == "restore-baseline":
        restore_baseline()
    else:
        finish()


if __name__ == "__main__":
    main()
