import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.responses import AUTH_NO_STORE_HEADERS, error, fail
from app.core.observability import emit_event, request_client_network, route_template
from app.domain.errors import (
    AppError,
    AuthenticationError,
    AuthenticationRateLimitedError,
    AuthorizationError,
    AvatarTooLargeError,
    ConflictError,
    EmailDeliveryFailedError,
    FileTooLargeError,
    InputError,
    IntegrityVerificationError,
    ResourceNotFoundError,
    ServerStorageLowError,
    StorageQuotaExceededError,
    StorageUnavailableError,
    UploadDailyLimitError,
)

_STATUS_BY_ERROR_TYPE: dict[type[AppError], int] = {
    AuthenticationRateLimitedError: 429,
    UploadDailyLimitError: 429,
    StorageQuotaExceededError: 413,
    ServerStorageLowError: 507,
    AuthenticationError: 401,
    AuthorizationError: 403,
    ResourceNotFoundError: 404,
    ConflictError: 409,
    AvatarTooLargeError: 413,
    FileTooLargeError: 413,
    InputError: 422,
    StorageUnavailableError: 503,
    EmailDeliveryFailedError: 503,
    IntegrityVerificationError: 409,
}


def _response_headers(request: Request, error_value: AppError | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    app_settings = getattr(request.app.state, "settings", None)
    api_prefix = getattr(app_settings, "API_PREFIX", "/api/v1").rstrip("/")
    sensitive_prefixes = tuple(
        f"{api_prefix}/{segment}"
        for segment in ("auth", "keys", "files", "audit-logs", "recovery", "admin")
    )
    route = request.scope.get("route")
    route_tags = getattr(route, "tags", ())
    is_sensitive_route = bool(
        {"Auth", "Keys", "Files", "Sharing", "Recovery", "Audit Logs", "Admin"}.intersection(
            route_tags
        )
    )
    is_sensitive_path = any(
        request.url.path == prefix or request.url.path.startswith(f"{prefix}/")
        for prefix in sensitive_prefixes
    )
    if is_sensitive_route or is_sensitive_path:
        headers.update(AUTH_NO_STORE_HEADERS)
    if error_value is not None:
        headers.update(error_value.headers)
    return headers


def _status_for(error_value: AppError) -> int:
    for error_type, status_code in _STATUS_BY_ERROR_TYPE.items():
        if isinstance(error_value, error_type):
            return status_code
    return 400


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Return useful validation details without echoing secret request input."""
    return [
        {
            "location": list(item.get("loc", ())),
            "message": item.get("msg", "Invalid value"),
            "type": item.get("type", "value_error"),
        }
        for item in exc.errors()
    ]


def _request_event_fields(request: Request) -> dict[str, object]:
    return {
        "request_id": getattr(request.state, "request_id", "unknown"),
        "method": request.method,
        "route_template": route_template(request),
        "client_network": request_client_network(request),
    }


def _observe_app_error(request: Request, exc: AppError) -> None:
    observability = getattr(request.app.state, "observability", None)
    fields = _request_event_fields(request)
    fields["error_code"] = exc.code

    if isinstance(exc, AuthenticationRateLimitedError):
        if observability is not None:
            observability.increment("auth_rate_limited_total")
        emit_event("auth.rate_limited", level=logging.WARNING, **fields)
    elif isinstance(exc, AuthenticationError):
        if observability is not None:
            observability.increment("auth_failures_total")
        emit_event("auth.failure", level=logging.INFO, **fields)
    elif isinstance(exc, StorageUnavailableError):
        if observability is not None:
            observability.increment("storage_failures_total")
        emit_event("storage.unavailable", level=logging.ERROR, **fields)
    elif isinstance(exc, IntegrityVerificationError):
        if observability is not None:
            observability.increment("integrity_failures_total")
        emit_event("storage.integrity_failure", level=logging.WARNING, **fields)


def register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        _observe_app_error(request, exc)
        return fail(
            message=exc.message,
            data={"error_code": exc.code, "details": exc.details},
            code=_status_for(exc),
            headers=_response_headers(request, exc),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return fail(
            message="Request validation failed",
            data={
                "error_code": "request_validation_failed",
                "details": _safe_validation_errors(exc),
            },
            code=422,
            headers=_response_headers(request),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        observability = getattr(request.app.state, "observability", None)
        if observability is not None:
            observability.increment("unhandled_errors_total")
        emit_event(
            "application.unhandled_error",
            level=logging.ERROR,
            error_type=type(exc).__name__,
            **_request_event_fields(request),
        )
        return error(
            message="Internal server error",
            data={"error_code": "internal_error"},
            code=500,
            headers=_response_headers(request),
        )
