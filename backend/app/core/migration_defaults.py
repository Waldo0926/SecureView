from __future__ import annotations

import re

_MYSQL_CURRENT_TIMESTAMP = re.compile(
    r"^(current_timestamp|now|localtime|localtimestamp)(?:\(([0-6]?)\))?$",
    re.IGNORECASE,
)


def _canonical_mysql_timestamp_default(value: str | None) -> str | None:
    if value is None:
        return None

    candidate = "".join(value.strip().split())
    while candidate.startswith("(") and candidate.endswith(")"):
        candidate = candidate[1:-1]

    match = _MYSQL_CURRENT_TIMESTAMP.fullmatch(candidate)
    if match is None:
        return None

    function_name = match.group(1).lower()
    if function_name == "now" and "(" not in candidate:
        return None

    precision = match.group(2)
    if precision in {None, "", "0"}:
        return "current_timestamp"
    return f"current_timestamp({precision})"


def mysql_timestamp_defaults_equivalent(
    inspected_default: str | None,
    rendered_metadata_default: str | None,
) -> bool:
    """Compare only MySQL's equivalent current-timestamp spellings."""
    inspected = _canonical_mysql_timestamp_default(inspected_default)
    rendered = _canonical_mysql_timestamp_default(rendered_metadata_default)
    return inspected is not None and inspected == rendered
