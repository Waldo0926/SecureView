"""`mcs21-deploy` checks that the live backend reports the commit it just deployed.

`live_commit` is extracted from the real script and run in bash with `curl` replaced by a
function that prints a canned health response, so the test exercises the exact parsing the
server runs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "deployment" / "server" / "mcs21-deploy"
SHA = "0123456789abcdef0123456789abcdef01234567"


def _function(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert match, f"{name} not found in mcs21-deploy"
    return match.group(0)


def _live_commit(curl_body: str, curl_status: int = 0) -> subprocess.CompletedProcess[str]:
    program = "\n".join(
        [
            "set -Eeuo pipefail",
            "public_host=203.0.113.1",
            "health_url=http://127.0.0.1/health/live",
            f"curl() {{ printf '%s' '{curl_body}'; return {curl_status}; }}",
            _function("live_commit"),
            'printf "[%s]" "$(live_commit || true)"',
        ]
    )
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)


def test_reads_the_commit_from_the_health_response() -> None:
    result = _live_commit(f'{{"status":"ok","commit":"{SHA}"}}')

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"[{SHA}]"


def test_prints_nothing_for_an_unknown_commit() -> None:
    assert _live_commit('{"status":"ok","commit":null}').stdout == "[]"
    assert _live_commit('{"status":"ok"}').stdout == "[]"


def test_prints_nothing_when_the_probe_fails() -> None:
    assert _live_commit("", curl_status=22).stdout == "[]"


def test_deploy_rolls_back_when_the_live_commit_differs() -> None:
    deploy = _function("deploy_release")
    health = deploy.index("if ! verify_live; then")
    check = deploy.index('if [[ "$live_sha" != "$sha" ]]; then')
    success = deploy.index('audit success "commit=$sha')

    assert health < check < success
    mismatch = deploy[check:success]
    assert 'restore_previous "$old_target"' in mismatch
    assert "die " in mismatch
