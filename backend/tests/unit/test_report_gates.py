"""The two scripts that decide whether CI test reports can be trusted and published."""

from __future__ import annotations

import base64
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BACKEND_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hygiene = _load("check_report_hygiene")
no_skips = _load("check_no_skips")


CLEAN_JUNIT = (
    '<testsuites><testsuite><testcase classname="a" name="registers e2e-bob@example.com"/>'
    "</testsuite></testsuites>"
)


def test_a_clean_report_passes(tmp_path: Path) -> None:
    (tmp_path / "junit.xml").write_text(CLEAN_JUNIT)

    assert hygiene.main(["check", str(tmp_path)]) == 0


@pytest.mark.parametrize(
    ("leak", "finding"),
    [
        ("-----BEGIN PRIVATE KEY-----\nMIIE", "PEM block"),
        ("-----BEGIN PUBLIC KEY-----\nMIIB", "PEM block"),
        ("token was rt_" + "a" * 43, "session token"),
        ("Authorization: Bearer " + "x" * 40, "bearer credential"),
        ("expected owner someone@secureview.tech", "email address outside the example domains"),
        ("decrypted: MCS21 demo file, generated today", "fixture plaintext"),
    ],
    # Plain ids: the default would put these very strings into the JUnit test names,
    # and the published report would then fail its own scan.
    ids=["private-pem", "public-pem", "session-token", "bearer", "real-email", "plaintext"],
)
def test_each_kind_of_leak_is_caught(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], leak: str, finding: str
) -> None:
    (tmp_path / "junit.xml").write_text(f"<failure>{leak}</failure>")

    assert hygiene.main(["check", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert finding in err
    # The finding is named; the secret itself is never echoed back into the CI log.
    assert leak not in err


def _zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _playwright_report(members: dict[str, str]) -> str:
    """The shape of Playwright's index.html: results inlined as a base64 ZIP data URL."""
    payload = base64.b64encode(_zip(members)).decode()
    return (
        '<html><script id="playwrightReportBase64" type="application/zip">'
        f"data:application/zip;base64,{payload}</script></html>"
    )


LEAK = "Authorization: Bearer " + "x" * 40


def test_a_leak_inside_a_compressed_attachment_is_caught(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Deflated, the credential is not in the file's bytes; only unpacking finds it.
    blob = _zip({"error-context.md": LEAK * 5})
    assert LEAK.encode() not in blob
    (tmp_path / "attachment.zip").write_bytes(blob)

    assert hygiene.main(["check", str(tmp_path)]) == 1
    assert "attachment.zip!error-context.md: bearer credential" in capsys.readouterr().err


def test_a_leak_inside_the_playwright_html_report_is_caught(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "index.html").write_text(
        _playwright_report({"report.json": '{"error": "-----BEGIN PRIVATE KEY-----"}'})
    )

    assert hygiene.main(["check", str(tmp_path)]) == 1
    assert "index.html#embedded-0!report.json: PEM block" in capsys.readouterr().err


def test_a_clean_playwright_html_report_passes(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        _playwright_report({"report.json": '{"title": "registers pw-bob@example.com"}'})
    )

    assert hygiene.main(["check", str(tmp_path)]) == 0


def test_a_playwright_trace_is_refused_without_being_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing in it matches a pattern; a trace is refused for what it records, not for
    # what a scan happens to find.
    (tmp_path / "trace.zip").write_bytes(_zip({"trace.trace": "{}", "trace.network": "{}"}))

    assert hygiene.main(["check", str(tmp_path)]) == 1
    assert "Playwright trace" in capsys.readouterr().err


def test_reserved_example_domains_are_allowed() -> None:
    assert hygiene.scan_text("a@example.com b@example.invalid c@EXAMPLE.org") == []


def test_no_skips_accepts_a_fully_executed_report(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(CLEAN_JUNIT)

    assert no_skips.main(["check", str(report)]) == 0


def test_no_skips_rejects_a_vitest_style_skipped_case(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="src/x.test.ts" name="live">'
        "<skipped/></testcase></testsuite></testsuites>"
    )

    assert no_skips.main(["check", str(report)]) == 1
