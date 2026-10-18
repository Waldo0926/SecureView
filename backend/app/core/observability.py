from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_EVENT_LOGGER = logging.getLogger("secureview.events")
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "token",
    "password",
    "passphrase",
    "secret",
    "private",
    "public_key",
    "pem",
    "filename",
    "file_name",
    "content",
    "body",
    "email",
    "username",
    "user_agent",
)
_METRIC_NAMES = (
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


def configure_event_logger(log_level: str) -> None:
    """Configure only SecureView's structured event logger.

    Uvicorn owns the process logging configuration. These events deliberately propagate into
    that existing handler so staging receives one JSON line per security/operations event in
    journald without a second file handler or a second copy of the message.
    """

    _EVENT_LOGGER.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    _EVENT_LOGGER.propagate = True


def _redacted_field(key: str, value: Any) -> Any:
    normalized = key.lower()
    if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value.replace("\r", " ").replace("\n", " ")[:256]
    if isinstance(value, Mapping):
        return {str(k): _redacted_field(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redacted_field(key, item) for item in value]
    return str(value)[:256]


def emit_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one compact JSON event after redacting risky field names.

    Callers should still pass only operational metadata. This function is a final guard, not
    permission to pass request bodies, exception messages, file names, keys, or credentials.
    """

    payload: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "event": event,
    }
    payload.update({key: _redacted_field(key, value) for key, value in fields.items()})
    _EVENT_LOGGER.log(
        level,
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return str(template) if template else "<unmatched>"


def request_client_network(request: Request) -> str:
    """Return a redacted client network, never the exact address.

    Production Uvicorn accepts proxy headers only from 127.0.0.1, so request.client is already
    the client selected by that trusted-proxy boundary. This helper then reduces IPv4 to /24
    and IPv6 to /64 before it can reach an operations log.
    """

    if request.client is None:
        return "unknown"
    try:
        address = ip_address(request.client.host)
    except ValueError:
        return "unknown"
    if isinstance(address, IPv4Address):
        return str(ip_network(f"{address}/24", strict=False))
    if isinstance(address, IPv6Address):
        return str(ip_network(f"{address}/64", strict=False))
    return "unknown"  # pragma: no cover - ipaddress currently has only v4/v6


class ObservabilityState:
    """Small process-local counters for the loopback-only operations snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters = {name: 0 for name in _METRIC_NAMES}
        self._started_at = datetime.now(UTC)
        self._started_monotonic = time.monotonic()
        self._readiness_state = "unknown"

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self._counters:
            raise KeyError(f"Unknown observability counter: {name}")
        if amount < 0:
            raise ValueError("Observability counters cannot decrease")
        with self._lock:
            self._counters[name] += amount

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            readiness_state = self._readiness_state
        return {
            "process_started_at": self._started_at.isoformat(timespec="seconds"),
            "uptime_seconds": max(0, int(time.monotonic() - self._started_monotonic)),
            "readiness_state": readiness_state,
            **counters,
        }

    def mark_readiness(
        self,
        state: str,
        *,
        expected_schema: str | None = None,
        observed_schema: str | None = None,
    ) -> None:
        with self._lock:
            previous = self._readiness_state
            if previous == state:
                return
            self._readiness_state = state
            if state != "ready":
                self._counters["readiness_failures_total"] += 1
                if state == "schema_incompatible":
                    self._counters["schema_mismatch_total"] += 1

        if state == "ready":
            if previous not in {"unknown", "ready"}:
                emit_event(
                    "readiness.recovered",
                    previous_state=previous,
                )
            return

        fields: dict[str, Any] = {"readiness_state": state, "previous_state": previous}
        if state == "schema_incompatible":
            fields.update(
                {
                    "expected_schema": expected_schema,
                    "observed_schema": observed_schema,
                }
            )
        emit_event("readiness.failed", level=logging.ERROR, **fields)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Count requests and mirror recovery state changes as redacted JSON events."""

    def __init__(self, app, *, state: ObservabilityState, api_prefix: str) -> None:
        super().__init__(app)
        self.state = state
        self.recovery_prefix = f"{api_prefix.rstrip('/')}/recovery"

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = secrets.token_hex(8)
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)

        self.state.increment("requests_total")
        if 400 <= response.status_code < 500:
            self.state.increment("responses_4xx_total")
        elif response.status_code >= 500:
            self.state.increment("responses_5xx_total")

        template = route_template(request)
        if request.method == "POST" and template.startswith(self.recovery_prefix):
            self.state.increment("recovery_operations_total")
            emit_event(
                "recovery.operation",
                level=logging.INFO if response.status_code < 400 else logging.WARNING,
                request_id=request_id,
                method=request.method,
                route_template=template,
                status_code=response.status_code,
                result="success" if response.status_code < 400 else "failure",
                client_network=request_client_network(request),
                duration_ms=round((time.monotonic() - started) * 1000, 1),
            )

        response.headers["X-Request-ID"] = request_id
        return response
