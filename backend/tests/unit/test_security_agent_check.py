"""The daily security-agent check: its exit status, and a journal line with nothing personal in it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.schemas.agent_schema import (
    AgentCountsOut,
    AgentFindingOut,
    AgentInputSummaryOut,
    AgentReportOut,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "security_agent_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("security_agent_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load()

# Everything a finding can carry that must never reach the journal.
PRIVATE = ("mallory", "victim-admin", "203.0.113.66", "salaries-2026.xlsx", "Account:")


def _finding(rule_id: str, priority: str) -> AgentFindingOut:
    return AgentFindingOut(
        rule_id=rule_id,
        priority=priority,
        title=f"victim-admin signed in after mallory guessed from 203.0.113.66 ({rule_id})",
        summary="salaries-2026.xlsx",
        evidence=["Account: victim-admin", "Source address: 203.0.113.66"],
        recommended_action="Disable mallory",
    )


def _report(*findings: AgentFindingOut, capped: list[str] | None = None) -> AgentReportOut:
    counts = {
        p: sum(1 for f in findings if f.priority == p.upper())
        for p in ("critical", "high", "medium", "low")
    }
    return AgentReportOut(
        generated_at="2026-10-02T06:00:00Z",
        window_hours=24,
        counts=AgentCountsOut(**counts),
        findings=list(findings),
        rules=[],
        inputs=AgentInputSummaryOut(
            audit_events_read=3,
            event_types_capped=capped or [],
            files_checkable=1,
            files_never_checked=0,
            audit_chain_entries_verified=10,
        ),
        boundaries=[],
    )


def _run(report: AgentReportOut, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    status = check.main(lambda: report)
    out, err = capsys.readouterr()
    return status, out, err


def test_a_quiet_day_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    status, out, err = _run(_report(), capsys)

    assert status == 0 and err == ""
    assert json.loads(out) == {
        "window_hours": 24,
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "rules_fired": [],
        "event_types_capped": [],
    }


def test_medium_and_low_findings_do_not_fail_the_unit(capsys: pytest.CaptureFixture[str]) -> None:
    report = _report(
        _finding("LOGIN_GUESSING_SOURCE", "MEDIUM"), _finding("SIGN_IN_THROTTLE_ACTIVE", "LOW")
    )

    status, out, err = _run(report, capsys)

    assert status == 0 and err == ""
    summary = json.loads(out)
    assert summary["medium"] == 1 and summary["low"] == 1
    assert summary["rules_fired"] == ["LOGIN_GUESSING_SOURCE", "SIGN_IN_THROTTLE_ACTIVE"]


@pytest.mark.parametrize("priority", ["HIGH", "CRITICAL"])
def test_any_high_or_critical_finding_exits_three(
    priority: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, err = _run(_report(_finding("SIGN_IN_AFTER_GUESSING", priority)), capsys)

    assert status == check.FINDINGS_EXIT_STATUS == 3
    assert json.loads(out)["rules_fired"] == ["SIGN_IN_AFTER_GUESSING"]
    assert "1 critical/high finding(s)" in err and "Admin -> Security agent" in err


def test_the_output_never_names_an_account_an_address_or_a_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report(
        _finding("SIGN_IN_AFTER_GUESSING", "CRITICAL"),
        _finding("INTEGRITY_DAMAGE", "CRITICAL"),
        _finding("DOWNLOAD_BURST", "HIGH"),
        capped=["FILE_DOWNLOAD_AUTHORIZED"],
    )

    status, out, err = _run(report, capsys)

    assert status == 3
    for private in PRIVATE:
        assert private not in out and private not in err
    summary = json.loads(out)
    assert summary["critical"] == 2 and summary["high"] == 1
    assert summary["event_types_capped"] == ["FILE_DOWNLOAD_AUTHORIZED"]
    # Rule ids are listed once each, in a stable order.
    assert summary["rules_fired"] == [
        "DOWNLOAD_BURST",
        "INTEGRITY_DAMAGE",
        "SIGN_IN_AFTER_GUESSING",
    ]


def test_the_check_runs_the_scheduled_report_over_one_day() -> None:
    source = SCRIPT.read_text()

    assert check.WINDOW_HOURS == 24
    assert "report_for_scheduled_check(window_hours=WINDOW_HOURS)" in source
    # It must not print anything from a finding beyond its rule id.
    assert ".title" not in source and ".evidence" not in source and ".summary" not in source
