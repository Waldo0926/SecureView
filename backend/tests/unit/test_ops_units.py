"""Static checks on the server-only ops units and scripts (issues #57 and #59).

None of these files can be exercised in CI -- they drive systemd, docker and the staging
host's own paths -- so the facts the staging runbooks rely on are pinned here instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3] / "deployment" / "server"


def _read(name: str) -> str:
    return (SERVER / name).read_text(encoding="utf-8")


def _directives(name: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in _read(name).splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        found.setdefault(key.strip(), []).append(value.strip())
    return found


def test_reconcile_runs_as_the_app_account_on_the_real_storage_root() -> None:
    unit = _directives("mcs21-reconcile.service")

    assert unit["User"] == ["fypapp"] and unit["Group"] == ["fypapp"]
    assert unit["ReadWritePaths"] == ["/var/lib/fyp-secure-file-platform"]
    assert unit["EnvironmentFile"] == ["/etc/fyp-secure-file-platform/backend.env"]
    assert unit["ProtectSystem"] == ["strict"]
    assert unit["OnFailure"] == ["mcs21-alert@%n.service"]
    assert "mcs21-backup.service" in unit["After"][0].split()
    (exec_start,) = unit["ExecStart"]
    assert "scripts/reconcile.py --apply --max-deletions " in exec_start


def test_reconcile_refuses_to_start_without_a_recent_same_host_backup() -> None:
    (pre,) = _directives("mcs21-reconcile.service")["ExecStartPre"]

    assert pre.startswith("+/bin/sh -c ")
    assert "flock -w" in pre and "/run/lock/mcs21-backup.lock" in pre
    assert "/var/backups/mcs21-daily" in pre and "-mmin -180" in pre
    # `$$` is systemd's escape for a literal `$`; a bare `$(` would be expanded by systemd.
    assert "$$(find" in pre and re.search(r"(?<!\$)\$\(", pre) is None


def test_reconcile_timer_fires_after_the_daily_backup_window() -> None:
    timer = _directives("mcs21-reconcile.timer")

    assert timer["OnCalendar"] == ["*-*-* 05:00:00 Asia/Kuala_Lumpur"]
    assert "RandomizedDelaySec" not in timer


def test_the_integrity_sweep_only_reads_storage_and_runs_after_the_backup_and_reconcile() -> None:
    unit = _directives("mcs21-integrity-sweep.service")

    assert unit["User"] == ["fypapp"] and unit["Group"] == ["fypapp"]
    assert unit["EnvironmentFile"] == ["/etc/fyp-secure-file-platform/backend.env"]
    assert unit["ReadOnlyPaths"] == ["/var/lib/fyp-secure-file-platform"]
    assert "ReadWritePaths" not in unit and unit["ProtectSystem"] == ["strict"]
    (exec_start,) = unit["ExecStart"]
    assert "scripts/integrity_sweep.py" in exec_start
    # The sweep must not be able to change what it checks.
    assert "restore_file" not in exec_start and "--apply" not in exec_start
    timer = _directives("mcs21-integrity-sweep.timer")
    assert timer["OnCalendar"] == ["*-*-* 05:30:00 Asia/Kuala_Lumpur"]


def test_every_ops_job_alerts_on_failure() -> None:
    for name in (
        "mcs21-reconcile.service",
        "mcs21-integrity-sweep.service",
        "mcs21-security-agent.service",
        "mcs21-offsite-backup.service",
        "mcs21-observe.service",
        "mcs21-audit-checkpoint.service",
        "mcs21-backup.service.d/alert.conf",
        "mcs21-backup-verify.service.d/alert.conf",
    ):
        assert _directives(name).get("OnFailure") == ["mcs21-alert@%n.service"], name
    # The alert unit itself must not alert, or a broken mail setup would loop.
    assert "OnFailure" not in _directives("mcs21-alert@.service")


def test_the_alert_never_puts_the_api_key_on_a_command_line_or_journal_in_email() -> None:
    script = _read("mcs21-alert")

    assert (SERVER / "mcs21-alert").stat().st_mode & 0o111
    assert '--header @"$work/headers"' in script
    assert re.search(r"curl[^\n]*RESEND_API_KEY|curl[^\n]*\$api_key", script) is None
    assert "unset api_key" in script
    assert "source " not in script and "\n. " not in script
    assert "journalctl --no-pager --output" not in script
    assert "Journal output is intentionally withheld from email" in script
    assert "Inspect locally: sudo journalctl -u" in script
    # The security agent's mail adds a fixed pointer to the admin tab, never its output.
    assert 'if unit == "mcs21-security-agent.service":' in script
    assert "open Admin -> Security agent" in script


def test_observability_watcher_is_redacted_hardened_and_thresholded() -> None:
    unit = _directives("mcs21-observe.service")
    source = _read("mcs21-observe.service")
    timer = _directives("mcs21-observe.timer")

    assert unit["User"] == ["fypapp"] and unit["Group"] == ["fypapp"]
    assert unit["StateDirectory"] == ["mcs21-observe"]
    assert unit["ProtectSystem"] == ["strict"]
    assert unit["NoNewPrivileges"] == ["true"]
    assert unit["OnFailure"] == ["mcs21-alert@%n.service"]
    for expected in (
        "--max-auth-rate-limited 5",
        "--max-auth-failures 50",
        "--max-storage-failures 3",
        "--max-integrity-failures 3",
        "--max-unhandled-errors 3",
        "--max-disk-percent 85",
        "--max-checkpoint-age-seconds 7200",
    ):
        assert expected in source
    assert timer["OnCalendar"] == ["*:0/5"]
    assert timer["Persistent"] == ["true"]


def test_audit_checkpoint_key_stays_out_of_the_app_process() -> None:
    unit = _directives("mcs21-audit-checkpoint.service")
    source = _read("mcs21-audit-checkpoint.service")
    timer = _directives("mcs21-audit-checkpoint.timer")

    assert unit["User"] == ["root"] and unit["Group"] == ["root"]
    assert unit["ProtectSystem"] == ["strict"]
    assert unit["NoNewPrivileges"] == ["true"]
    assert unit["OnFailure"] == ["mcs21-alert@%n.service"]
    assert unit["EnvironmentFile"] == [
        "/etc/fyp-secure-file-platform/backup.env",
        "/etc/fyp-secure-file-platform/audit-checkpoint.env",
    ]
    assert "audit-checkpoint.key" in source
    assert "backend.env" not in source
    assert "--allow-local-dest" not in source
    assert timer["OnCalendar"] == ["*-*-* *:15:00"]
    assert timer["Persistent"] == ["true"]


def test_trusted_proxy_and_internal_metrics_stay_on_loopback() -> None:
    deploy = _read("mcs21-deploy")
    nginx = _read("nginx-secureview.conf")

    assert "--proxy-headers --forwarded-allow-ips=127.0.0.1" in deploy
    assert "--host 127.0.0.1" in deploy
    assert "--forwarded-allow-ips=*" not in deploy
    assert "proxy_pass http://127.0.0.1:8000" in nginx
    assert "location ^~ /internal/" in nginx
    assert "return 404;" in nginx
    assert "proxy_pass http://127.0.0.1:8000/internal" not in nginx


def test_backup_verify_derives_its_expectations() -> None:
    script = _read("mcs21-backup-verify")

    assert "0002_auth_identity_sessions" not in script
    assert "-m alembic heads" in script
    assert 'expected="$live_tables|$expected_version|1"' in script
    assert "CHECK TABLE" in script


def test_the_security_agent_check_reads_the_database_only_and_runs_after_the_sweep() -> None:
    unit = _directives("mcs21-security-agent.service")

    assert unit["User"] == ["fypapp"] and unit["Group"] == ["fypapp"]
    assert unit["EnvironmentFile"] == ["/etc/fyp-secure-file-platform/backend.env"]
    assert unit["ProtectSystem"] == ["strict"] and unit["NoNewPrivileges"] == ["true"]
    assert unit["OnFailure"] == ["mcs21-alert@%n.service"]
    # No write path anywhere, and not even read access to the stored objects.
    assert "ReadWritePaths" not in unit and "StateDirectory" not in unit
    assert unit["InaccessiblePaths"] == ["/var/lib/fyp-secure-file-platform"]
    assert unit["ExecStart"] == [
        "/opt/mcs21/current/backend/.venv/bin/python scripts/security_agent_check.py"
    ]
    timer = _directives("mcs21-security-agent.timer")
    assert timer["OnCalendar"] == ["*-*-* 06:00:00 Asia/Kuala_Lumpur"]
    assert timer["Persistent"] == ["true"]
    assert timer["Unit"] == ["mcs21-security-agent.service"]
    # After the 05:30 sweep, so a file it has just found damaged is in the same morning's run.
    (sweep,) = _directives("mcs21-integrity-sweep.timer")["OnCalendar"]
    assert sweep.split()[1] < timer["OnCalendar"][0].split()[1]


# --- a release may install its two ops timers by itself, and nothing else ------------------


def _acceptable(
    tmp_path: Path, service_text: str, timer_text: str, name: str = "mcs21-integrity-sweep"
) -> bool:
    """Run the deploy script's own `ops_unit_acceptable` against the given unit text."""
    script = _read("mcs21-deploy")
    match = re.search(r"^ops_unit_acceptable\(\) \{\n.*?^\}\n", script, flags=re.S | re.M)
    assert match, "ops_unit_acceptable is missing from mcs21-deploy"
    (tmp_path / "x.service").write_text(service_text)
    (tmp_path / "x.timer").write_text(timer_text)
    result = subprocess.run(
        [
            "bash",
            "-c",
            match.group(0)
            + f'\nops_unit_acceptable "{tmp_path}/x.service" "{tmp_path}/x.timer" {name}',
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to run the deploy script's check"
)
@pytest.mark.parametrize("name", ["mcs21-integrity-sweep", "mcs21-security-agent"])
def test_the_deploy_script_accepts_exactly_the_shipped_units(tmp_path: Path, name: str) -> None:
    service = _read(f"{name}.service")
    timer = _read(f"{name}.timer")

    def ok(service_text: str, timer_text: str = timer) -> bool:
        return _acceptable(tmp_path, service_text, timer_text, name)

    assert ok(service)
    # Each of these would turn "a commit that passed CI" into code run with more privilege.
    assert not ok(service.replace("User=fypapp", "User=root"))
    assert not ok(service.replace("Group=fypapp", "Group=root"))
    assert not ok(
        service.replace(
            "ExecStart=/opt/mcs21/current/backend/.venv/bin/python", "ExecStart=/bin/sh"
        )
    )
    assert not ok(service.replace("ExecStart=/opt/mcs21", "ExecStart=+/opt/mcs21"))
    assert not ok(service + "\nExecStartPost=+/bin/sh -c id\n")
    assert not ok(service, timer.replace(f"Unit={name}.service", "Unit=other.service"))


def test_the_deploy_script_installs_only_the_closed_list_and_never_fails_a_good_release() -> None:
    script = _read("mcs21-deploy")

    (line,) = [entry for entry in script.splitlines() if entry.startswith("ops_units=")]
    assert line == "ops_units=(mcs21-integrity-sweep mcs21-security-agent)"
    # Called after the release is live and audited, and guarded so a failure only warns.
    deploy = script.split("deploy_release() {", 1)[1].split("rollback_release() {", 1)[0]
    assert deploy.index('audit success "commit=$sha') < deploy.index('install_ops_units "$release"')
    assert 'if ! install_ops_units "$release"; then' in deploy
    assert "systemd-analyze verify" in script and "cmp -s" in script


def _pip_installer(tmp_path: Path, behaviour: str) -> tuple[Path, Path]:
    """A shell that defines install_backend_requirements exactly as mcs21-deploy does, with a
    fake venv python whose `pip install` follows `behaviour` ("hang" or "fail" per call, then succeed)."""
    script = _read("mcs21-deploy")
    body = script.split('pip_attempts="', 1)[1].split("build_release() {", 1)[0]
    build = tmp_path / "build"
    python = build / "backend" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    (build / "backend" / "requirements.txt").write_text("", encoding="utf-8")
    calls = tmp_path / "calls"
    python.write_text(
        "#!/bin/bash\n"
        f'n=$(( $(cat "{calls}" 2>/dev/null || echo 0) + 1 )); echo "$n" > "{calls}"\n'
        f'step=$(echo "{behaviour}" | cut -d, -f"$n")\n'
        'case "$step" in hang) sleep 30 ;; fail) exit 1 ;; *) exit 0 ;; esac\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    runner = tmp_path / "run.sh"
    runner.write_text(
        "set -Eeuo pipefail\n"
        'as_deploy() { "$@"; }\n'
        f'pip_attempts="{body}'
        'install_backend_requirements "$1"\n',
        encoding="utf-8",
    )
    return runner, calls


@pytest.mark.skipif(shutil.which("timeout") is None, reason="needs coreutils timeout")
def test_a_stalled_pip_install_is_cut_off_and_tried_again(tmp_path: Path) -> None:
    runner, calls = _pip_installer(tmp_path, "hang,ok")
    env = {"PATH": "/usr/bin:/bin", "MCS21_PIP_ATTEMPT_SECONDS": "1", "MCS21_PIP_RETRY_PAUSE": "0"}
    result = subprocess.run(
        ["bash", str(runner), str(tmp_path / "build")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().strip() == "2"
    assert "attempt 1 of 3 failed or ran past 1s" in result.stderr


@pytest.mark.skipif(shutil.which("timeout") is None, reason="needs coreutils timeout")
def test_pip_gives_up_after_its_attempts(tmp_path: Path) -> None:
    runner, calls = _pip_installer(tmp_path, "fail,fail,fail,ok")
    env = {"PATH": "/usr/bin:/bin", "MCS21_PIP_ATTEMPT_SECONDS": "5", "MCS21_PIP_RETRY_PAUSE": "0"}
    result = subprocess.run(
        ["bash", str(runner), str(tmp_path / "build")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert calls.read_text().strip() == "3"


def test_a_failed_requirements_install_removes_its_build_directory() -> None:
    build = (
        _read("mcs21-deploy").split("build_release() {", 1)[1].split("backup_database() {", 1)[0]
    )
    assert 'if ! install_backend_requirements "$build_dir"; then' in build
    guarded = build.split('if ! install_backend_requirements "$build_dir"; then', 1)[1].split(
        "fi", 1
    )[0]
    assert 'rm -rf "$build_dir"' in guarded and "die " in guarded
    assert "pip install" not in build, "pip must only run through install_backend_requirements"
