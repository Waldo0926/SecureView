"""The deploy gate: the server deploys only what CI has promoted, and CI promotes only green.

These are structural checks on two files that are easy to change separately and wrongly. A
workflow job added without being listed in `promote.needs` would let a commit be marked safe
while that job is red; a server script that fetched `main` again would silently bypass the gate.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
if not WORKFLOW.exists():
    # The public snapshot keeps the team workflow under ci/ (it runs on the team's own
    # runners); the checks below are about that file, not about the workflow that runs here.
    WORKFLOW = REPO_ROOT / "ci/ci.yml"
SCRIPT = REPO_ROOT / "deployment/server/mcs21-auto-deploy"


def _job_names(workflow: str) -> list[str]:
    jobs_block = workflow.split("\njobs:\n", maxsplit=1)[1]
    return re.findall(r"^  ([a-z0-9-]+):\s*$", jobs_block, flags=re.MULTILINE)


def _promote_block(workflow: str) -> str:
    start = workflow.index("\n  promote:\n")
    return workflow[start:]


def test_promote_waits_for_every_other_job() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    others = {name for name in _job_names(workflow) if name != "promote"}
    needs = re.search(r"^    needs: \[([^\]]*)\]", _promote_block(workflow), flags=re.MULTILINE)

    assert needs is not None, "promote must declare needs"
    assert others, "no jobs were found, so the check proves nothing"
    assert {item.strip() for item in needs.group(1).split(",")} == others


def test_docs_only_check_compares_a_push_with_the_deploy_branch() -> None:
    # A docs-only push can cancel the run of the code commit before it. If the push were
    # compared with that commit, the tests would be skipped, promote with them, and the code
    # would never reach deploy. Compared with deploy, the code is still part of the diff.
    workflow = WORKFLOW.read_text(encoding="utf-8")
    changes = workflow[workflow.index("\n  changes:\n") : workflow.index("\n  backend:\n")]

    assert "git fetch --no-tags --quiet origin deploy" in changes
    assert 'from="FETCH_HEAD"' in changes
    assert "github.event.before" not in changes


def test_promote_runs_only_for_pushes_to_main_and_only_moves_forward() -> None:
    block = _promote_block(WORKFLOW.read_text(encoding="utf-8"))

    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in block
    assert "contents: write" in block
    assert "force=false" in block
    assert "have diverged" in block
    # Never a force push, and never a push of commits that touch workflows (GITHUB_TOKEN
    # cannot do that): the ref is moved through the API.
    assert "git push" not in block
    assert "--force" not in block


def test_promote_is_the_only_job_with_write_access() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("contents: write") == 1


def test_server_deploys_the_promoted_branch_not_main() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "deploy_branch=deploy" in script
    assert 'target_sha="$(remote_sha)"' in script
    # remote_sha must read the deploy branch; main is fetched only because the release
    # command requires the deployed commit to be reachable from it.
    remote_sha = re.search(r"remote_sha\(\) \{\n(.*?)\n\}", script, flags=re.DOTALL)
    assert remote_sha is not None
    assert "refs/heads/$deploy_branch" in remote_sha.group(1)
    assert "refs/heads/main" not in remote_sha.group(1)


def test_server_fails_closed_when_nothing_has_been_promoted() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    missing = script.index("is missing on origin")
    assert "exit 0" in script[missing : missing + 400]  # nothing deploys, but no failed unit


def test_server_never_walks_a_manual_release_back() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'merge-base --is-ancestor "$target_sha" "$deployed_sha"' in script


def test_server_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
