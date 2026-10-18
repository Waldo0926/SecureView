"""Put one damaged ciphertext object back from an encrypted backup set.

The question this answers is "a stored file was modified; how do we get the original back?".
Objects are write-once: a stored ciphertext never changes legitimately, so a backup copy whose
SHA-256 equals the digest the system recorded for the file is, byte for byte, the original. That
copy is the "last known good version"; there is no version history to choose from, only
backups that either hold the right bytes or do not.

The digest it must match is the one recorded in the audit chain when the file was uploaded
(`FILE_UPLOADED.metadata.ciphertext_sha256`), falling back to `files.encrypted_sha256` for files
uploaded before the audit row carried it. If the two disagree, someone rewrote the column
together with the object; the audit-chain digest wins, and the column is repaired.

What it refuses, changing nothing:

* a backup set whose artifacts do not match `index.json`, do not decrypt and authenticate under
  this private key and this set's manifest id, or whose archive does not match its manifest;
* a set that does not hold this object, or holds different bytes for it than the recorded digest
  (an object uploaded after the set was taken is not in it: try a later set);
* an extracted object whose SHA-256 or size is not the recorded one.

Nothing is written unless `--apply` is given. With it, the damaged bytes are first copied to a
quarantine directory (they are evidence), the good bytes replace the object atomically, the
file is re-verified by the same rule that condemned it, and `FILE_RESTORED_FROM_BACKUP` goes
into the audit chain. The backup private key stays with its custodian and is only brought to
the machine for the duration of the restore, exactly as for `restore_drill.py`.

Two sources, tried in this order of convenience:

* **The same-host nightly backup** (`/var/backups/mcs21-daily`, written by `mcs21-backup` and
  kept 14 days), when no `--backup-set` is given. The newest `mcs21-files-<stamp>.tar.gz` is
  checked against its `.sha256` manifest, the one object is read out of it and compared with the
  recorded digest; a set that holds the damaged bytes (taken after the tampering) is skipped and
  the next older one tried. No key is needed: that backup is plaintext ciphertext on the same
  disk, protected only by root. This is the command the Admin Integrity tab shows, and it runs
  as pasted.
* **An encrypted off-site set** (`--backup-set <dir> --private-key <pem>`), for a server whose
  disk is gone or whose nightly copies are also suspect. The custodian brings the private key
  for the duration of the restore, exactly as for `restore_drill.py`.

Run on the server from `backend/`. As root, it loads `/etc/fyp-secure-file-platform/backend.env`
itself and gives the restored object back to the service account, so the Integrity tab's command
needs no `systemd-run`:

    sudo .venv/bin/python scripts/restore_file.py --file-id <uuid>            # report only
    sudo .venv/bin/python scripts/restore_file.py --file-id <uuid> --apply    # write
    .venv/bin/python scripts/restore_file.py --file-id <uuid> \\
        --backup-set /mnt/offsite/20260924T091500Z-3f9c2a1b --private-key /media/custodian/backup_priv.pem

The encrypted archive is one authenticated stream, so the whole `objects.tar.enc` is decrypted to
check it before the one object is taken out; that costs the same as a restore of the objects.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_encrypted import (
    ARTIFACTS,
    MANIFEST_ID_RE,
    envelope_context,
    is_object_key,
)
from backup_envelope import (
    EnvelopeError,
    decrypt_file,
    load_private_key,
    sha256_file,
)


class RestoreRefused(Exception):
    """The restore was stopped before anything was written."""


@dataclass(frozen=True)
class LocatedObject:
    path: Path
    sha256: str
    size_bytes: int
    manifest_id: str


# Written by deployment/server/mcs21-backup: mcs21-files-<stamp>.tar.gz is `tar -C <data dir> .`
# and mcs21-<stamp>.sha256 is `sha256sum` over the dump and the tar. Overridable for tests and
# for a server that keeps them elsewhere.
DAILY_BACKUP_DIR = Path(os.getenv("MCS21_DAILY_BACKUP_DIR", "/var/backups/mcs21-daily"))
DEPLOYMENT_ENV_FILE = Path("/etc/fyp-secure-file-platform/backend.env")


def load_deployment_env(path: Path = DEPLOYMENT_ENV_FILE) -> bool:
    """Put the deployment's variables into the environment when nothing set them.

    The service account gets them from systemd's EnvironmentFile=. Root, pasting the command the
    Integrity tab shows, has nothing, and `Settings` would then fall back to development values
    and point at the wrong database. Only variables not already set are added, and only when
    DB_HOST is absent, so a `systemd-run` or an exported environment is left alone.
    """
    if os.getenv("DB_HOST") or not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


def daily_backup_files(directory: Path) -> list[Path]:
    """The nightly object archives, newest first."""
    return sorted(directory.glob("mcs21-files-*.tar.gz"), reverse=True)


def _daily_manifest_digest(archive: Path) -> str | None:
    """The SHA-256 that mcs21-backup recorded for this archive, or None if there is no manifest."""
    stamp = archive.name[len("mcs21-files-") : -len(".tar.gz")]
    manifest = archive.with_name(f"mcs21-{stamp}.sha256")
    if not manifest.is_file():
        return None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].endswith(archive.name):
            return parts[0]
    return None


def locate_in_daily_backups(
    directory: Path,
    *,
    object_key: str,
    data_relative_dir: PurePosixPath,
    trusted_sha256: str,
    expected_size: int | None,
    work: Path,
) -> LocatedObject:
    """The verified bytes of `object_key` from the newest nightly archive that holds the original.

    `data_relative_dir` is where the object store sits under the directory the archive was taken
    from (`encrypted`, for `/var/lib/fyp-secure-file-platform/encrypted`). An archive whose own
    checksum manifest does not match is skipped as damaged; one that holds other bytes for the
    object was taken after the tampering and is skipped too; the first match wins.
    """
    archives = daily_backup_files(directory)
    if not archives:
        raise RestoreRefused(
            f"no nightly backup archives in {directory}: give --backup-set and --private-key "
            "for an encrypted off-site set"
        )
    member_name = f"./{PurePosixPath(data_relative_dir, object_key)}"
    skipped: list[str] = []
    for archive in archives:
        recorded = _daily_manifest_digest(archive)
        if recorded is not None and sha256_file(archive) != recorded:
            skipped.append(f"{archive.name}: does not match its .sha256 manifest")
            continue
        candidate = work / f"candidate-{archive.name}.ciphertext"
        found = False
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                if member.name not in (member_name, member_name[2:]):
                    continue
                if not member.isfile():
                    break
                source = tar.extractfile(member)
                assert source is not None
                with candidate.open("xb") as out:
                    while chunk := source.read(1024 * 1024):
                        out.write(chunk)
                found = True
                break
        if not found:
            skipped.append(f"{archive.name}: does not hold the object")
            continue
        digest = sha256_file(candidate)
        size = candidate.stat().st_size
        if digest != trusted_sha256 or (expected_size is not None and size != expected_size):
            skipped.append(f"{archive.name}: holds different bytes (taken after the damage?)")
            candidate.unlink()
            continue
        return LocatedObject(
            path=candidate, sha256=digest, size_bytes=size, manifest_id=archive.name
        )
    raise RestoreRefused(
        "no nightly backup holds the original: " + "; ".join(skipped) + ". If the file was "
        "uploaded after the newest backup it is in no backup yet; otherwise try an encrypted "
        "off-site set with --backup-set and --private-key"
    )


def _give_back_to_service_account(paths: list[Path | None], reference: Path) -> None:
    """Files written by root must end up owned like the object store, or the API cannot read them."""
    if os.geteuid() != 0:
        return
    try:
        stat = reference.stat()
    except OSError:
        return
    for path in paths:
        if path is not None and path.exists():
            os.chown(path, stat.st_uid, stat.st_gid)


def _decrypt(set_dir: Path, role: str, destination: Path, key, manifest_id: str) -> None:
    try:
        decrypt_file(
            set_dir / ARTIFACTS[role], destination, key, envelope_context(manifest_id, role)
        )
    except EnvelopeError as exc:
        raise RestoreRefused(f"{role} artifact: {exc}") from exc


def locate_object(
    set_dir: Path,
    key,
    *,
    object_key: str,
    trusted_sha256: str,
    expected_size: int | None,
    work: Path,
) -> LocatedObject:
    """Return the verified bytes of `object_key` from a backup set, or raise RestoreRefused."""
    index_path = set_dir / "index.json"
    if not index_path.is_file():
        raise RestoreRefused("index.json is missing: the backup set is incomplete")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    manifest_id = str(index.get("manifest_id", ""))
    if not MANIFEST_ID_RE.match(manifest_id) or set_dir.name != manifest_id:
        raise RestoreRefused(
            f"index manifest id {manifest_id!r} does not match set directory {set_dir.name!r}"
        )
    artifacts = index.get("artifacts", {})
    for role in ("manifest", "objects"):
        entry = artifacts.get(role) or {}
        path = set_dir / ARTIFACTS[role]
        if entry.get("file") != ARTIFACTS[role] or not path.is_file():
            raise RestoreRefused(f"{role} artifact {ARTIFACTS[role]} is missing")
        if sha256_file(path) != entry.get("sha256"):
            raise RestoreRefused(f"{role} artifact {ARTIFACTS[role]} does not match index.json")

    manifest_plain = work / "manifest.json"
    _decrypt(set_dir, "manifest", manifest_plain, key, manifest_id)
    manifest = json.loads(manifest_plain.read_text(encoding="utf-8"))
    if manifest.get("manifest_id") != manifest_id:
        raise RestoreRefused("manifest.json names a different manifest id than index.json")

    entries = {str(item["key"]): item for item in manifest.get("objects", [])}
    entry = entries.get(object_key)
    if entry is None:
        raise RestoreRefused(
            "this backup set does not hold the object (it was uploaded after the set was "
            "taken, or the set is from before it existed): try a later set"
        )
    if str(entry["sha256"]) != trusted_sha256:
        raise RestoreRefused(
            "this backup set holds different bytes for the object than the digest the system "
            "recorded for it; it is not the original, so it is not used"
        )
    if expected_size is not None and int(entry["bytes"]) != expected_size:
        raise RestoreRefused("the backup's copy has a different size than the recorded one")

    objects_plain = work / "objects.tar"
    _decrypt(set_dir, "objects", objects_plain, key, manifest_id)
    if sha256_file(objects_plain) != manifest["objects_tar"]["sha256"]:
        raise RestoreRefused("object archive does not match the manifest")

    candidate = work / "candidate.ciphertext"
    with tarfile.open(objects_plain, mode="r") as tar:
        marker = tar.extractfile("MANIFEST_ID")
        if (marker.read().decode().strip() if marker else "") != manifest_id:
            raise RestoreRefused("object archive belongs to a different backup set")
        member_name = f"objects/{object_key}"
        for member in tar:
            if member.name != member_name:
                continue
            relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
            if not member.isfile() or not is_object_key(relative):
                raise RestoreRefused(f"unexpected archive member {member.name!r}")
            source = tar.extractfile(member)
            assert source is not None
            with candidate.open("xb") as out:
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
            break
        else:
            raise RestoreRefused("the manifest lists the object but the archive does not hold it")

    digest = sha256_file(candidate)
    size = candidate.stat().st_size
    if digest != trusted_sha256 or size != int(entry["bytes"]):
        raise RestoreRefused("the extracted object does not match the recorded SHA-256 and size")
    return LocatedObject(path=candidate, sha256=digest, size_bytes=size, manifest_id=manifest_id)


def _private_key(path: Path):
    passphrase = os.getenv("BACKUP_PRIVATE_KEY_PASSPHRASE")
    if path.stat().st_mode & 0o077:
        print(
            "restore_file: warning: the private key file is readable by group/others",
            file=sys.stderr,
        )
    try:
        return load_private_key(path, passphrase.encode() if passphrase else None)
    except EnvelopeError:
        if passphrase is None and sys.stdin.isatty():
            return load_private_key(
                path, getpass.getpass("Backup private key passphrase: ").encode()
            )
        raise


def restore(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.domain.auth import RequestContext
    from app.repositories.file_repository import FileRepository
    from app.services.audit_log_service import AuditLogService
    from app.services.file_storage_service import (
        FileStorageService,
        StorageObjectError,
        StorageObjectMissingError,
    )
    from app.services.integrity_service import IntegrityService

    settings = get_settings()
    storage = FileStorageService(settings=settings)
    quarantine = (
        Path(args.quarantine_dir)
        if args.quarantine_dir
        else settings.ENCRYPTED_FILE_DIR.resolve(strict=False).parent / "quarantine"
    )
    context = RequestContext(user_agent="scripts/restore_file.py")

    with SessionLocal() as db:
        repository = FileRepository(db)
        file_record = repository.get_file_by_uuid(args.file_id, include_deleted=True)
        if file_record is None or file_record.status == "DELETED":
            raise RestoreRefused("no such file, or it has been deleted")

        anchor = repository.upload_anchor_sha256(file_record.file_uuid)
        trusted = anchor or file_record.encrypted_sha256
        digest_edited = anchor is not None and anchor != file_record.encrypted_sha256

        try:
            current, _ = storage.hash_object(file_record.storage_object_key)
            current_state = "intact" if current == trusted else "modified"
        except StorageObjectMissingError:
            current_state = "missing"
        except StorageObjectError:
            current_state = "unreadable"
        if current_state == "intact" and not digest_edited:
            print(json.dumps({"result": "nothing_to_restore", "file_id": file_record.file_uuid}))
            return 0

        with tempfile.TemporaryDirectory(prefix="fyp-restore-file-") as tmp:
            work = Path(tmp)
            os.chmod(work, 0o700)
            expected_size = None if digest_edited else file_record.encrypted_size_bytes
            if args.backup_set:
                located = locate_object(
                    Path(args.backup_set),
                    _private_key(Path(args.private_key)),
                    object_key=file_record.storage_object_key,
                    trusted_sha256=trusted,
                    expected_size=expected_size,
                    work=work,
                )
                source = "encrypted_set"
            else:
                object_root = settings.ENCRYPTED_FILE_DIR.resolve(strict=False)
                located = locate_in_daily_backups(
                    Path(args.daily_dir),
                    object_key=file_record.storage_object_key,
                    data_relative_dir=PurePosixPath(object_root.name),
                    trusted_sha256=trusted,
                    expected_size=expected_size,
                    work=work,
                )
                source = "nightly_backup"
            report = {
                "result": "restored" if args.apply else "dry_run_would_restore",
                "file_id": file_record.file_uuid,
                "source": source,
                "manifest_id": located.manifest_id,
                "ciphertext_sha256": located.sha256,
                "bytes": located.size_bytes,
                "stored_object": current_state,
                "recorded_digest_was_edited": digest_edited,
                "digest_source": "audit_chain" if anchor else "files_table",
            }
            if not args.apply:
                print(json.dumps(report))
                return 0

            kept = storage.replace_object(
                file_record.storage_object_key, located.path, quarantine_dir=quarantine
            )
            object_path = settings.ENCRYPTED_FILE_DIR.resolve(strict=False) / (
                file_record.storage_object_key
            )
            _give_back_to_service_account(
                [object_path, kept, quarantine], settings.ENCRYPTED_FILE_DIR.resolve(strict=False)
            )
            if digest_edited:
                file_record.encrypted_sha256 = trusted
                file_record.encrypted_size_bytes = located.size_bytes
                db.commit()
            integrity = IntegrityService(
                db=db,
                settings=settings,
                storage=storage,
                audit_service=AuditLogService(db),
                repository=repository,
            )
            result = integrity.verify_and_record(
                file_record, actor_user_id=None, context=context, source="restore"
            )
            if result != "VALID":
                raise RestoreRefused(
                    f"the restored object was written but verification says {result}; "
                    "check the storage volume"
                )
            AuditLogService(db).append(
                action="FILE_RESTORED_FROM_BACKUP",
                result="SUCCESS",
                resource_type="FILE",
                resource_id=file_record.file_uuid,
                context_user_agent=context.user_agent,
                metadata={
                    "manifest_id": located.manifest_id,
                    "ciphertext_sha256": located.sha256,
                    "stored_object_before": current_state,
                    "recorded_digest_repaired": digest_edited,
                    "damaged_copy_kept": kept is not None,
                },
            )
            db.commit()
            report["damaged_copy_kept"] = kept is not None
            print(json.dumps(report))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--file-id", required=True, type=UUID, help="the file's public UUID")
    parser.add_argument(
        "--backup-set",
        help="encrypted off-site set, directory <dest>/<manifest-id>; default: the nightly backup",
    )
    parser.add_argument("--private-key", help="PEM backup private key, with --backup-set")
    parser.add_argument(
        "--daily-dir",
        default=str(DAILY_BACKUP_DIR),
        help=f"where mcs21-backup keeps the nightly archives (default {DAILY_BACKUP_DIR})",
    )
    parser.add_argument(
        "--quarantine-dir", help="where the damaged bytes are kept before replacing them"
    )
    parser.add_argument("--apply", action="store_true", help="write; without it only report")
    args = parser.parse_args(argv)
    if bool(args.backup_set) != bool(args.private_key):
        parser.error("--backup-set and --private-key go together")
    return args


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        load_deployment_env()
        return restore(args)
    except RestoreRefused as exc:
        print(f"restore_file: REFUSED -- {exc}", file=sys.stderr)
        return 1
    except (EnvelopeError, OSError) as exc:
        print(f"restore_file: FAILED -- {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
