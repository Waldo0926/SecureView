"""Fail if a JUnit XML report (pytest or vitest) contains any skipped test.

`AUTH_TEST_DATABASE_URL` makes the MySQL integration suite skip itself instead of
failing when it is absent (see tests/integration/conftest.py). That is the right
default for a laptop without MySQL running, but it means "pytest -m integration
passed" is not by itself proof the database gate ran -- a misconfigured CI job
that never sets the URL would report a silent, all-green no-op. This script reads
back the JUnit report pytest wrote and turns any <skipped> element into a hard
failure of the CI step, so the release gate can only pass by actually running.

The frontend live-backend suites have the same shape -- each one skips itself without its
E2E_* environment -- so the `e2e-live` job runs this over vitest's JUnit report too.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_no_skips.py <junit.xml>", file=sys.stderr)
        return 2

    report_path = Path(argv[1])
    if not report_path.is_file():
        print(f"check_no_skips: report not found: {report_path}", file=sys.stderr)
        return 2

    tree = ET.parse(report_path)
    skipped_tests = []
    for testcase in tree.getroot().iter("testcase"):
        skipped_element = testcase.find("skipped")
        if skipped_element is not None:
            name = f"{testcase.get('classname', '')}::{testcase.get('name', '')}"
            reason = skipped_element.get("message", "").strip()
            skipped_tests.append((name, reason))

    if skipped_tests:
        print(
            f"check_no_skips: {len(skipped_tests)} test(s) were skipped in "
            f"{report_path.name} -- this gate requires every integration test to "
            "actually execute:",
            file=sys.stderr,
        )
        for name, reason in skipped_tests:
            print(f"  SKIPPED {name}: {reason}", file=sys.stderr)
        return 1

    print(f"check_no_skips: no skipped tests in {report_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
