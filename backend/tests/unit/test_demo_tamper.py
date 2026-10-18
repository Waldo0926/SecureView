"""The demo tamper tool after the file was put back from backup instead of by its own `restore`.

Rehearsing the defence runs flip, then the Admin Integrity tab's restore_file.py command. The
copy demo_tamper.py kept must then read as stale, or the next flip is refused.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo_tamper = _load("demo_tamper")

ORIGINAL = b"the original ciphertext bytes " * 10


def _kept(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """A stored object with the original and its row kept beside it, as `flip` leaves them."""
    digest = hashlib.sha256(ORIGINAL).hexdigest()
    saved_bytes = tmp_path / "id.orig"
    saved_row = tmp_path / "id.json"
    saved_bytes.write_bytes(ORIGINAL)
    saved_row.write_text(json.dumps({"encrypted_sha256": digest, "status": "ACTIVE"}))
    obj = tmp_path / "obj.ciphertext"
    obj.write_bytes(ORIGINAL)
    return obj, saved_bytes, saved_row, digest


def test_a_file_still_flipped_is_not_mistaken_for_restored(tmp_path) -> None:
    obj, saved_bytes, saved_row, digest = _kept(tmp_path)
    demo_tamper._flip_one_byte(obj)

    assert demo_tamper._already_put_back(obj, saved_bytes, saved_row, digest) is False


def test_a_file_restored_from_backup_makes_the_kept_copy_stale(tmp_path) -> None:
    obj, saved_bytes, saved_row, digest = _kept(tmp_path)
    demo_tamper._flip_one_byte(obj)
    obj.write_bytes(ORIGINAL)  # what restore_file.py --apply does

    assert demo_tamper._already_put_back(obj, saved_bytes, saved_row, digest) is True


def test_a_forged_digest_left_in_the_row_is_not_stale(tmp_path) -> None:
    obj, saved_bytes, saved_row, _ = _kept(tmp_path)
    obj.write_bytes(ORIGINAL)

    assert demo_tamper._already_put_back(obj, saved_bytes, saved_row, "0" * 64) is False


def test_nothing_kept_is_not_stale(tmp_path) -> None:
    obj = tmp_path / "obj.ciphertext"
    obj.write_bytes(ORIGINAL)

    assert (
        demo_tamper._already_put_back(obj, tmp_path / "none.orig", tmp_path / "none.json", "x")
        is False
    )
