from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    get_admin_service,
    get_request_context,
    get_security_agent_service,
    require_admin,
)
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiSuccessResponse, ok
from app.core.time import to_api_utc
from app.domain.auth import ActorContext, RequestContext
from app.schemas.admin_schema import (
    AdminFileListResponse,
    AdminFileOut,
    AdminIntegrityReportOut,
    AdminIntegrityScanOut,
    AdminPasswordResetOut,
    AdminStatsOut,
    AdminUserDetailOut,
    AdminUserListResponse,
    AdminUserOut,
    AdminUserStatusResponse,
)
from app.schemas.agent_schema import AgentReportOut
from app.services.admin_service import AdminService
from app.services.security_agent_service import SecurityAgentService

router = APIRouter()

AdminActorDependency = Annotated[ActorContext, Depends(require_admin)]
AdminServiceDependency = Annotated[AdminService, Depends(get_admin_service)]
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]
AgentServiceDependency = Annotated[SecurityAgentService, Depends(get_security_agent_service)]


@router.get("/users", response_model=ApiSuccessResponse[AdminUserListResponse])
def list_users(
    actor: AdminActorDependency,
    service: AdminServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    status: Annotated[
        Literal["ACTIVE", "DISABLED", "DELETED", "CURRENT"] | None,
        Query(description="One status, or CURRENT for everything not deleted. Omit for all."),
    ] = None,
) -> JSONResponse:
    rows = service.list_users(actor=actor, limit=limit, offset=offset, status=status)
    data = AdminUserListResponse(
        users=[AdminUserOut(**_user_fields(user)) for user in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )
    return ok(message="Users retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


def _user_fields(user) -> dict:
    return {
        "user_id": UUID(user.user_uuid),
        "username": user.username,
        "email": user.email,
        "email_verified": bool(user.email_verified),
        "role": user.role,
        "status": user.status,
        "created_at": to_api_utc(user.created_at),
        "last_login_at": to_api_utc(user.last_login_at),
        "password_changed_at": to_api_utc(user.password_changed_at),
    }


@router.get("/users/{user_id}", response_model=ApiSuccessResponse[AdminUserDetailOut])
def get_user(
    user_id: UUID,
    actor: AdminActorDependency,
    service: AdminServiceDependency,
) -> JSONResponse:
    user, activity = service.user_detail(actor=actor, user_id=user_id)
    data = AdminUserDetailOut(
        **_user_fields(user),
        file_count=activity.file_count,
        stored_bytes=activity.stored_bytes,
        shared_by_them=activity.shared_by_them,
        shared_with_them=activity.shared_with_them,
        active_sessions=activity.active_sessions,
    )
    return ok(message="User retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=ApiSuccessResponse[AdminPasswordResetOut],
)
def reset_user_password(
    user_id: UUID,
    actor: AdminActorDependency,
    context: RequestContextDependency,
    service: AdminServiceDependency,
) -> JSONResponse:
    user, temporary, revoked, notice_sent = service.reset_user_password(
        actor=actor, user_id=user_id, context=context
    )
    data = AdminPasswordResetOut(
        user_id=user_id,
        username=user.username,
        temporary_password=temporary,
        revoked_sessions=revoked,
        notice_sent=notice_sent,
    )
    # no-store: the temporary password must not sit in any cache between here and the browser.
    return ok(message="Login password reset", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.get("/stats", response_model=ApiSuccessResponse[AdminStatsOut])
def platform_stats(
    actor: AdminActorDependency,
    service: AdminServiceDependency,
) -> JSONResponse:
    data = service.platform_stats(actor=actor)
    return ok(message="Platform statistics retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


# One request must not hash the whole store: a few large objects can take minutes. The batch
# size and the time budget both stop the pass; the report says how many files are left, and
# the scheduled sweep (deployment/server/mcs21-integrity-sweep.*) covers the rest.
SCAN_BATCH_FILES = 50
SCAN_BUDGET_SECONDS = 20.0


@router.get("/integrity", response_model=ApiSuccessResponse[AdminIntegrityReportOut])
def integrity_report(
    actor: AdminActorDependency,
    service: AdminServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> JSONResponse:
    data = service.integrity_report(actor=actor, limit=limit)
    return ok(message="Integrity report retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.post("/integrity/scan", response_model=ApiSuccessResponse[AdminIntegrityScanOut])
def scan_integrity(
    actor: AdminActorDependency,
    context: RequestContextDependency,
    service: AdminServiceDependency,
) -> JSONResponse:
    data = service.scan_integrity(
        actor=actor,
        context=context,
        limit=SCAN_BATCH_FILES,
        budget_seconds=SCAN_BUDGET_SECONDS,
    )
    return ok(message="Integrity scan finished", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.get("/agent/report", response_model=ApiSuccessResponse[AgentReportOut])
def security_agent_report(
    actor: AdminActorDependency,
    service: AgentServiceDependency,
    window_hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> JSONResponse:
    """The security agent's ranked findings. Read-only, metadata only, rule-based."""
    data = service.report(actor=actor, window_hours=window_hours)
    return ok(message="Security agent report generated", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.get("/files", response_model=ApiSuccessResponse[AdminFileListResponse])
def list_all_files(
    actor: AdminActorDependency,
    service: AdminServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    status: Annotated[
        Literal["ACTIVE", "CORRUPTED", "DELETED", "CURRENT"] | None,
        Query(description="One status, or CURRENT for everything not deleted. Omit for all."),
    ] = None,
) -> JSONResponse:
    rows = service.list_files(actor=actor, limit=limit, offset=offset, status=status)
    data = AdminFileListResponse(
        files=[
            AdminFileOut(
                file_id=UUID(file.file_uuid),
                owner_id=UUID(owner.user_uuid),
                owner_username=owner.username,
                original_filename=file.original_filename,
                mime_type=file.mime_type,
                file_size=file.file_size_bytes,
                encrypted_size=file.encrypted_size_bytes,
                status=file.status,
                created_at=to_api_utc(file.created_at),
                updated_at=to_api_utc(file.updated_at),
            )
            for file, owner in rows[:limit]
        ],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )
    return ok(message="Files retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


def _set_status(
    *,
    user_id: UUID,
    enabled: bool,
    actor: ActorContext,
    context: RequestContext,
    service: AdminService,
) -> JSONResponse:
    user, changed, revoked = service.set_user_enabled(
        actor=actor,
        user_id=user_id,
        enabled=enabled,
        context=context,
    )
    data = AdminUserStatusResponse(
        user_id=user_id,
        status=user.status,
        changed=changed,
        revoked_sessions=revoked,
    )
    return ok(message="User status updated", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.post(
    "/users/{user_id}/disable",
    response_model=ApiSuccessResponse[AdminUserStatusResponse],
)
def disable_user(
    user_id: UUID,
    actor: AdminActorDependency,
    context: RequestContextDependency,
    service: AdminServiceDependency,
) -> JSONResponse:
    return _set_status(
        user_id=user_id,
        enabled=False,
        actor=actor,
        context=context,
        service=service,
    )


@router.post(
    "/users/{user_id}/enable",
    response_model=ApiSuccessResponse[AdminUserStatusResponse],
)
def enable_user(
    user_id: UUID,
    actor: AdminActorDependency,
    context: RequestContextDependency,
    service: AdminServiceDependency,
) -> JSONResponse:
    return _set_status(
        user_id=user_id,
        enabled=True,
        actor=actor,
        context=context,
        service=service,
    )
