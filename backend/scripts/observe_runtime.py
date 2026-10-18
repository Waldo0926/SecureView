#!/usr/bin/env python3
"""Read loopback-only runtime metrics and fail once when an alert threshold is crossed.

The systemd unit wraps this script with OnFailure=mcs21-alert@%n.service. The state file keeps
only counters and active breach codes; it contains no request data, credentials, file names,
or user identifiers. A persistent breach stays visible in every JSON snapshot but does not
send the same email every five minutes. If a new breach appears, the unit fails again.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_COUNTERS = (
    "requests_total",
    "responses_4xx_total",
    "responses_5xx_total",
    "auth_failures_total",
    "auth_rate_limited_total",
    "storage_failures_total",
    "integrity_failures_total",
    "unhandled_errors_total",
    "readiness_failures_total",
    "schema_mismatch_total",
    "recovery_operations_total",
)


class ObserveError(Exception):
    pass


def _json_line(event: str, **fields: Any) -> str:
    return json.dumps(
        {"event": event, **fields},
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_loopback_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ObserveError("metrics and health URLs must be loopback HTTP endpoints")


def fetch_json(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    _require_loopback_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SecureView-ops-watch/1.0"},
    )
    try:
        # URL/error detail can contain environment data; do not print it.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ObserveError(f"loopback probe failed ({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise ObserveError("loopback probe did not return a JSON object")
    return payload


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObserveError("observability state file is unreadable") from exc
    if not isinstance(payload, dict):
        raise ObserveError("observability state file has an invalid shape")
    return payload


def write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, temporary = tempfile.mkstemp(prefix=".observability-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def disk_used_percent(path: Path) -> float:
    stats = os.statvfs(path)
    total = stats.f_blocks * stats.f_frsize
    available = stats.f_bavail * stats.f_frsize
    if total <= 0:
        raise ObserveError("disk capacity could not be determined")
    return round((total - available) * 100.0 / total, 2)


def checkpoint_age_seconds(path: Path, *, now: float | None = None) -> float | None:
    if not path.exists():
        return None
    current = time.time() if now is None else now
    return max(0.0, current - path.stat().st_mtime)


def counter_deltas(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[dict[str, int], bool]:
    restarted = previous is None or previous.get("process_started_at") != current.get(
        "process_started_at"
    )
    deltas: dict[str, int] = {}
    for name in _COUNTERS:
        value = int(current.get(name, 0))
        before = 0 if restarted or previous is None else int(previous.get(name, 0))
        deltas[name] = 0 if restarted else max(0, value - before)
    return deltas, restarted


def evaluate_breaches(
    *,
    health: dict[str, Any],
    deltas: dict[str, int],
    disk_percent: float,
    checkpoint_age: float | None,
    args: argparse.Namespace,
) -> list[str]:
    breaches: list[str] = []
    if health.get("status") != "ready":
        breaches.append("backend_not_ready")
    if deltas["auth_rate_limited_total"] >= args.max_auth_rate_limited:
        breaches.append("auth_rate_limit_burst")
    if deltas["auth_failures_total"] >= args.max_auth_failures:
        breaches.append("auth_failure_burst")
    if deltas["storage_failures_total"] >= args.max_storage_failures:
        breaches.append("storage_failure_burst")
    if deltas["integrity_failures_total"] >= args.max_integrity_failures:
        breaches.append("integrity_failure_burst")
    if deltas["unhandled_errors_total"] >= args.max_unhandled_errors:
        breaches.append("unhandled_error_burst")
    if deltas["schema_mismatch_total"] > 0:
        breaches.append("schema_mismatch")
    if disk_percent >= args.max_disk_percent:
        breaches.append("disk_pressure")
    if checkpoint_age is None or checkpoint_age > args.max_checkpoint_age_seconds:
        breaches.append("audit_checkpoint_stale")
    return sorted(breaches)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--metrics-url",
        default="http://127.0.0.1:8000/internal/metrics",
    )
    parser.add_argument(
        "--health-url",
        default="http://127.0.0.1:8000/health/ready",
    )
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--disk-path", type=Path, required=True)
    parser.add_argument("--checkpoint-stamp", type=Path, required=True)
    parser.add_argument("--max-auth-rate-limited", type=int, default=5)
    parser.add_argument("--max-auth-failures", type=int, default=50)
    parser.add_argument("--max-storage-failures", type=int, default=3)
    parser.add_argument("--max-integrity-failures", type=int, default=3)
    parser.add_argument("--max-unhandled-errors", type=int, default=3)
    parser.add_argument("--max-disk-percent", type=float, default=85.0)
    parser.add_argument("--max-checkpoint-age-seconds", type=int, default=7200)
    args = parser.parse_args(argv)
    for name in (
        "max_auth_rate_limited",
        "max_auth_failures",
        "max_storage_failures",
        "max_integrity_failures",
        "max_unhandled_errors",
        "max_checkpoint_age_seconds",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if not 1 <= args.max_disk_percent <= 100:
        parser.error("--max-disk-percent must be between 1 and 100")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        metrics = fetch_json(args.metrics_url)
        health = fetch_json(args.health_url)
        previous = load_state(args.state_file)
        deltas, restarted = counter_deltas(metrics, previous)
        disk_percent = disk_used_percent(args.disk_path)
        checkpoint_age = checkpoint_age_seconds(args.checkpoint_stamp)
        breaches = evaluate_breaches(
            health=health,
            deltas=deltas,
            disk_percent=disk_percent,
            checkpoint_age=checkpoint_age,
            args=args,
        )
        previous_breaches = set(previous.get("active_breaches", [])) if previous else set()
        new_breaches = sorted(set(breaches) - previous_breaches)
        recovered = sorted(previous_breaches - set(breaches))

        state = {
            "process_started_at": metrics.get("process_started_at"),
            **{name: int(metrics.get(name, 0)) for name in _COUNTERS},
            "active_breaches": breaches,
        }
        write_state(args.state_file, state)

        print(
            _json_line(
                "ops.metrics_snapshot",
                health_status=health.get("status", "unknown"),
                process_restarted=restarted,
                disk_used_percent=disk_percent,
                checkpoint_age_seconds=(
                    None if checkpoint_age is None else round(checkpoint_age, 1)
                ),
                deltas=deltas,
                active_breaches=breaches,
                recovered_breaches=recovered,
            )
        )
        if new_breaches:
            print(
                _json_line(
                    "ops.alert_threshold",
                    new_breaches=new_breaches,
                    active_breaches=breaches,
                ),
                file=sys.stderr,
            )
            return 2
        return 0
    except ObserveError as exc:
        print(
            _json_line(
                "ops.watch_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # keep unknown exception text out of journals
        print(
            _json_line(
                "ops.watch_failed",
                error_type=type(exc).__name__,
                error="unexpected observer failure",
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
