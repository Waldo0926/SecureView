"""Run the security agent once over the last 24 hours, and fail when it finds something urgent.

Until this existed the agent only analysed when an administrator opened the Security agent tab,
so a takeover or a tampered file waited for someone to look. The daily unit
`mcs21-security-agent` runs this script; a non-zero exit fails the unit and its OnFailure=
alert mails the team.

What it prints is deliberately thin: how many findings there are per priority and which rule ids
fired. Never usernames, addresses, file names or finding titles. The journal is not the place
for them, and the alert mail carries no journal content anyway; the details stay behind the
administrator login, on the Security agent tab.

Exit status is 0 when nothing is Critical or High, and 3 when anything is. Exit 3 means
"findings", not a crash. A Critical finding that stays unresolved (a damaged file that has not
been restored, say) fails the unit, and mails, every day until it is fixed: that is intended.

Like the agent itself it is read-only: it never writes to the database or the audit log.

Run from `backend/` with the deployment environment loaded:

    .venv/bin/python scripts/security_agent_check.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.schemas.agent_schema import AgentReportOut
from app.services.security_agent_service import SecurityAgentService

WINDOW_HOURS = 24
FINDINGS_EXIT_STATUS = 3


def summarise(report: AgentReportOut) -> tuple[dict[str, object], int]:
    """The journal line and the exit status. Counts and rule ids only."""
    counts = report.counts
    summary: dict[str, object] = {
        "window_hours": report.window_hours,
        "critical": counts.critical,
        "high": counts.high,
        "medium": counts.medium,
        "low": counts.low,
        "rules_fired": sorted({finding.rule_id for finding in report.findings}),
        "event_types_capped": sorted(report.inputs.event_types_capped),
    }
    urgent = counts.critical + counts.high
    return summary, FINDINGS_EXIT_STATUS if urgent else 0


def _scheduled_report() -> AgentReportOut:
    with SessionLocal() as db:
        return SecurityAgentService(db=db).report_for_scheduled_check(window_hours=WINDOW_HOURS)


def main(build: Callable[[], AgentReportOut] = _scheduled_report) -> int:
    report = build()
    summary, status = summarise(report)
    print(json.dumps(summary))
    if status:
        urgent = report.counts.critical + report.counts.high
        print(
            f"security_agent_check: {urgent} critical/high finding(s); "
            "open Admin -> Security agent for the details",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
