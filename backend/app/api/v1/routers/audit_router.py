from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.dependencies import get_audit_query_service, get_current_actor
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiSuccessResponse, ok
from app.core.time import to_api_utc
from app.domain.auth import ActorContext
from app.schemas.audit_schema import (
    AuditChainVerificationResponse,
    AuditLogListResponse,
    AuditLogOut,
    AuditLogQuery,
    FileAuditLogListResponse,
)
from app.services.audit_query_service import AuditQueryService

router = APIRouter()

ActorDependency = Annotated[ActorContext, Depends(get_current_actor)]
AuditServiceDependency = Annotated[AuditQueryService, Depends(get_audit_query_service)]


def _output(
    service: AuditQueryService,
    row,
    labels: dict[str, tuple[str, bool]] | None = None,
) -> AuditLogOut:
    log, actor_user, target_user = row
    file_name, file_deleted = (labels or {}).get(log.resource_id or "", (None, False))
    return AuditLogOut(
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        actor_user_id=UUID(actor_user.user_uuid) if actor_user is not None else None,
        actor_username=actor_user.username if actor_user is not None else None,
        target_user_id=UUID(target_user.user_uuid) if target_user is not None else None,
        target_username=target_user.username if target_user is not None else None,
        result=log.result,
        description=log.description,
        metadata=service.safe_metadata(log.metadata_json),
        created_at=to_api_utc(log.created_at),
        file_name=file_name,
        file_deleted=file_deleted,
    )


@router.get("", response_model=ApiSuccessResponse[AuditLogListResponse])
def list_audit_logs(
    actor: ActorDependency,
    service: AuditServiceDependency,
    query: Annotated[AuditLogQuery, Query()],
) -> JSONResponse:
    limit, offset = query.limit, query.offset
    rows = service.list_logs(actor=actor, limit=limit, offset=offset, filters=query)
    has_more = len(rows) > limit
    labels = service.file_labels(rows[:limit])
    data = AuditLogListResponse(
        logs=[_output(service, row, labels) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )
    return ok(message="Audit logs retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.get(
    "/file/{file_id}",
    response_model=ApiSuccessResponse[FileAuditLogListResponse],
)
def file_audit_logs(
    file_id: UUID,
    actor: ActorDependency,
    service: AuditServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> JSONResponse:
    rows = service.list_logs(actor=actor, limit=limit, offset=offset, file_id=file_id)
    has_more = len(rows) > limit
    labels = service.file_labels(rows[:limit])
    data = FileAuditLogListResponse(
        file_id=file_id,
        logs=[_output(service, row, labels) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )
    return ok(message="File audit logs retrieved", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.post(
    "/verify-chain",
    response_model=ApiSuccessResponse[AuditChainVerificationResponse],
)
def verify_chain(
    actor: ActorDependency,
    service: AuditServiceDependency,
) -> JSONResponse:
    result = service.verify_chain(actor=actor)
    return ok(
        message="Audit chain verified",
        data=AuditChainVerificationResponse.model_validate(result),
        headers=AUTH_NO_STORE_HEADERS,
    )
