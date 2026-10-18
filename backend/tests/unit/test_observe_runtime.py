from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND_ROOT / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


observe = _load("observe_runtime")


def _metrics(started: str = "2026-09-25T04:00:00+00:00", **overrides: int):
    value = {name: 0 for name in observe._COUNTERS}
    value.update(overrides)
    value["process_started_at"] = started
    return value


def _args() -> Namespace:
    return Namespace(
        max_auth_rate_limited=5,
        max_auth_failures=50,
        max_storage_failures=3,
        max_integrity_failures=3,
        max_unhandled_errors=3,
        max_disk_percent=85.0,
        max_checkpoint_age_seconds=7200,
    )


def test_counter_deltas_reset_when_process_restarts() -> None:
    previous = _metrics(auth_failures_total=100)
    current = _metrics(started="2026-09-25T05:00:00+00:00", auth_failures_total=2)

    deltas, restarted = observe.counter_deltas(current, previous)

    assert restarted is True
    assert deltas["auth_failures_total"] == 0


def test_thresholds_are_based_on_interval_deltas() -> None:
    previous = _metrics(
        auth_failures_total=100,
        auth_rate_limited_total=10,
        storage_failures_total=4,
        integrity_failures_total=7,
        unhandled_errors_total=2,
    )
    current = _metrics(
        auth_failures_total=151,
        auth_rate_limited_total=15,
        storage_failures_total=7,
        integrity_failures_total=10,
        unhandled_errors_total=5,
    )
    current["schema_mismatch_total"] = 1
    previous["schema_mismatch_total"] = 0
    deltas, restarted = observe.counter_deltas(current, previous)
    assert restarted is False

    breaches = observe.evaluate_breaches(
        health={"status": "ready"},
        deltas=deltas,
        disk_percent=85.0,
        checkpoint_age=7201,
        args=_args(),
    )

    assert breaches == sorted(
        [
            "audit_checkpoint_stale",
            "auth_failure_burst",
            "auth_rate_limit_burst",
            "disk_pressure",
            "integrity_failure_burst",
            "schema_mismatch",
            "storage_failure_burst",
            "unhandled_error_burst",
        ]
    )


def test_missing_checkpoint_and_failed_readiness_alert() -> None:
    deltas = {name: 0 for name in observe._COUNTERS}
    breaches = observe.evaluate_breaches(
        health={"status": "not_ready"},
        deltas=deltas,
        disk_percent=10.0,
        checkpoint_age=None,
        args=_args(),
    )
    assert breaches == ["audit_checkpoint_stale", "backend_not_ready"]
