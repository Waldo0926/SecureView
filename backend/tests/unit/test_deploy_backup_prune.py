"""`mcs21-deploy` keeps only the newest pre-deploy backup sets.

The function is extracted from the real script and run in bash against a temporary
directory, so the test exercises the exact code the server runs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deployment" / "server" / "mcs21-deploy"


def _function(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert match, f"{name} not found in mcs21-deploy"
    return match.group(0)


def _gnu_find() -> bool:
    if shutil.which("find") is None:
        return False
    result = subprocess.run(["find", "--version"], capture_output=True, text=True, check=False)
    return "GNU findutils" in result.stdout


pytestmark = pytest.mark.skipif(not _gnu_find(), reason="the server runs GNU find")


def _run(root: Path, keep: str) -> subprocess.CompletedProcess[str]:
    program = "\n".join(
        [
            "set -Eeuo pipefail",
            f"backup_root={root}",
            "die() { printf 'ERROR: %s\\n' \"$*\" >&2; exit 1; }",
            _function("prune_backups"),
            f'prune_backups "{keep}"',
        ]
    )
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)


def _make_sets(root: Path, count: int) -> list[str]:
    names = [f"202610{day:02d}T010000Z-{day:012x}" for day in range(1, count + 1)]
    for name in names:
        (root / name).mkdir()
        (root / name / "mysql-application.sql.gz").write_bytes(b"x")
    return names


def test_keeps_the_newest_sets_and_deletes_the_rest(tmp_path: Path) -> None:
    names = _make_sets(tmp_path, 14)

    result = _run(tmp_path, "10")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "4"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(names[-10:])


def test_never_touches_anything_it_did_not_create(tmp_path: Path) -> None:
    _make_sets(tmp_path, 12)
    (tmp_path / "manual-keep-me").mkdir()
    (tmp_path / "20261001T010000Z-notasha").mkdir()
    (tmp_path / "notes.txt").write_text("keep")

    assert _run(tmp_path, "10").returncode == 0
    assert (tmp_path / "manual-keep-me").is_dir()
    assert (tmp_path / "20261001T010000Z-notasha").is_dir()
    assert (tmp_path / "notes.txt").is_file()


def test_does_nothing_below_the_limit(tmp_path: Path) -> None:
    names = _make_sets(tmp_path, 5)

    result = _run(tmp_path, "10")

    assert result.stdout.strip() == "0"
    assert sorted(p.name for p in tmp_path.iterdir()) == names


@pytest.mark.parametrize("keep", ["0", "2", "ten", ""])
def test_refuses_to_keep_fewer_than_three(tmp_path: Path, keep: str) -> None:
    names = _make_sets(tmp_path, 5)

    result = _run(tmp_path, keep)

    assert result.returncode != 0
    assert sorted(p.name for p in tmp_path.iterdir()) == names
