"""Refuse to publish test reports that carry secrets, real addresses, or fixture content.

CI uploads JUnit and coverage reports as build artifacts (issue #58), and anyone who can
read the repository's Actions tab can download them. A passing report holds little more
than test names and line counts, but a *failing* one embeds assertion messages and
captured output -- which is exactly where a token, a key, or a decrypted file would land
if a test printed it. This scans every file under the given directories and fails if it
finds any of:

* a PEM block of any kind (private or public key material);
* a session token in this application's `at_`/`rt_` format, or any `Bearer` credential;
* an email address outside the reserved example domains the suites use;
* a known plaintext sentence from a test fixture, which would mean decrypted file content
  reached the report;
* a Playwright trace. A trace records every request header and body, DOM snapshots and
  typed values, so it is refused outright rather than scanned; CI never records one.

Archives are opened rather than read as bytes: a ZIP (a Playwright attachment, or a trace)
compresses its members, and the Playwright HTML report embeds its results as a base64 ZIP
inside `index.html`, so a byte-level scan of either would see nothing. Both are unpacked,
recursively, and every member is scanned the same way.

    .venv/bin/python scripts/check_report_hygiene.py reports/ other-reports/

It prints the file and the kind of finding, never the matched text itself.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "example.invalid"}

PATTERNS: dict[str, re.Pattern[str]] = {
    "PEM block": re.compile(r"-----BEGIN [A-Z0-9 ]+-----"),
    "session token": re.compile(r"\b(?:at|rt)_[A-Za-z0-9_\-]{20,}"),
    "bearer credential": re.compile(r"Bearer\s+[A-Za-z0-9._~+/\-]{16,}=*"),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")

# Plaintext the suites encrypt. If one of these appears in a report, a decrypted file (or
# the fixture itself) was printed by a failing test.
FIXTURE_PLAINTEXT = (
    "MCS21 demo file",
    "the server must never be able to read this sentence",
    "chapter one, and everything after it",
    "synthetic fixture bytes, not a real document",
    "uploaded before the passphrase reset",
    "end-to-end upload check",
)


# The Playwright HTML report inlines its results (test titles, steps, errors, stdout) as a
# base64 data URL of a ZIP in index.html.
EMBEDDED_ZIP = re.compile(rb"data:application/zip;base64,([A-Za-z0-9+/=]+)")
# Member names that only a Playwright trace contains.
TRACE_MEMBER = re.compile(r"(?:^|/)[^/]*\.(?:trace|network)$")
# Deeper than any real report nests; stops a crafted archive from recursing forever.
MAX_ARCHIVE_DEPTH = 4


def scan_text(text: str) -> list[str]:
    findings = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
    for match in EMAIL.finditer(text):
        if match.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
            findings.append("email address outside the example domains")
            break
    if any(sentinel in text for sentinel in FIXTURE_PLAINTEXT):
        findings.append("fixture plaintext")
    return findings


def _expand(label: str, data: bytes, depth: int = 0) -> Iterator[tuple[str, bytes | None]]:
    """Yield (label, bytes) for this blob and everything archived inside it.

    A `None` payload marks a Playwright trace, which is refused without being scanned.
    """
    yield label, data
    if depth >= MAX_ARCHIVE_DEPTH:
        return
    embedded = [match.group(1) for match in EMBEDDED_ZIP.finditer(data)]
    for index, payload in enumerate(embedded):
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            continue
        yield from _expand(f"{label}#embedded-{index}", decoded, depth + 1)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = f"{label}!{member.filename}"
            if TRACE_MEMBER.search(member.filename):
                yield name, None
                continue
            yield from _expand(name, archive.read(member), depth + 1)


def scan_file(path: Path) -> Iterator[tuple[str, str]]:
    """Yield (where, finding) for the file and every member of every archive inside it."""
    for label, data in _expand(str(path), path.read_bytes()):
        if data is None:
            yield label, "Playwright trace"
            continue
        for finding in scan_text(data.decode("utf-8", errors="replace")):
            yield label, finding


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: check_report_hygiene.py <report-dir> [<report-dir> ...]", file=sys.stderr)
        return 2

    files = []
    for root in map(Path, argv[1:]):
        if not root.exists():
            print(f"check_report_hygiene: {root} does not exist", file=sys.stderr)
            return 2
        files.extend(p for p in ([root] if root.is_file() else root.rglob("*")) if p.is_file())

    problems = 0
    for path in sorted(files):
        for where, finding in scan_file(path):
            problems += 1
            print(f"check_report_hygiene: {where}: {finding}", file=sys.stderr)

    if problems:
        print(
            f"check_report_hygiene: {problems} finding(s); refusing to publish these reports",
            file=sys.stderr,
        )
        return 1
    print(f"check_report_hygiene: {len(files)} report file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
