from __future__ import annotations

import base64
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    get_current_actor,
    get_recovery_service,
    get_request_context,
    require_admin,
    require_recovery_reviewer,
)
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiSuccessResponse, ok
from app.core.time import to_api_utc
from app.domain.auth import ActorContext, RequestContext
from app.repositories.recovery_repository import RecoveryRequestRecord
from app.schemas.recovery_schema import (
    RecoveryExecuteRequest,
    RecoveryExecutionKeyOut,
    RecoveryExecutionPackageOut,
    RecoveryKeyRegistrationResponse,
    RecoveryKeyStatusResponse,
    RecoveryPublicKeyOut,
    RecoveryPublicKeyRegisterRequest,
    RecoveryRejectRequest,
    RecoveryRequestActionResponse,
    RecoveryRequestCreate,
    RecoveryRequestListResponse,
    RecoveryRequestOut,
)
from app.services.recovery_service import RecoveryService

router = APIRouter()

ActorDependency = Annotated[ActorContext, Depends(get_current_actor)]
AdminActorDependency = Annotated[ActorContext, Depends(require_admin)]
ReviewerActorDependency = Annotated[ActorContext, Depends(require_recovery_reviewer)]
RecoveryServiceDependency = Annotated[RecoveryService, Depends(get_recovery_service)]
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _public_key_out(key) -> RecoveryPublicKeyOut:
    return RecoveryPublicKeyOut(
        key_id=UUID(key.key_uuid),
        algorithm=key.algorithm,
        key_size_bits=key.key_size_bits,
        public_key_pem=key.public_key_pem,
        fingerprint=key.fingerprint,
        status=key.status,
        created_at=to_api_utc(key.created_at),
    )


def _request_out(record: RecoveryRequestRecord) -> RecoveryRequestOut:
    request = record.request
    if record.target_key is None:  # pragma: no cover - migration/data invariant
        raise RuntimeError("Recovery request does not reference a public target key")
    return RecoveryRequestOut(
        request_id=UUID(request.request_uuid),
        file_id=UUID(record.file.file_uuid),
        requested_by=UUID(record.requester.user_uuid),
        target_key_id=UUID(record.target_key.key_uuid),
        reviewer_id=(UUID(record.reviewer.user_uuid) if record.reviewer is not None else None),
        executor_id=(UUID(record.executor.user_uuid) if record.executor is not None else None),
        reason=request.reason,
        rejection_reason=request.rejection_reason,
        status=request.status,
        created_at=to_api_utc(request.created_at),
        updated_at=to_api_utc(request.updated_at),
        expires_at=to_api_utc(request.expires_at),
        approved_at=to_api_utc(request.approved_at),
        rejected_at=to_api_utc(request.rejected_at),
        executed_at=to_api_utc(request.executed_at),
        cancelled_at=to_api_utc(request.cancelled_at),
    )


@router.get(
    "/public-key",
    response_model=ApiSuccessResponse[RecoveryPublicKeyOut],
)
def get_recovery_public_key(
    actor: ActorDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    key = service.get_public_key(actor=actor)
    return ok(
        message="Recovery public key retrieved",
        data=_public_key_out(key),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/public-key/register",
    response_model=ApiSuccessResponse[RecoveryKeyRegistrationResponse],
)
def register_recovery_public_key(
    payload: RecoveryPublicKeyRegisterRequest,
    actor: AdminActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    key, created, rotated = service.register_public_key(
        actor=actor,
        key_id=payload.key_id,
        public_key_pem=payload.public_key_pem,
        algorithm=payload.algorithm,
        context=context,
    )
    data = RecoveryKeyRegistrationResponse(
        key=_public_key_out(key),
        created=created,
        rotated_keys=rotated,
    )
    return ok(
        message="Recovery public key registered",
        data=data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/public-key/{key_id}/revoke",
    response_model=ApiSuccessResponse[RecoveryKeyStatusResponse],
)
def revoke_recovery_public_key(
    key_id: UUID,
    actor: AdminActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    key, changed = service.revoke_public_key(
        actor=actor,
        key_id=key_id,
        context=context,
    )
    data = RecoveryKeyStatusResponse(
        key_id=UUID(key.key_uuid),
        status="REVOKED",
        changed=changed,
    )
    return ok(
        message="Recovery public key revocation processed",
        data=data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/request",
    response_model=ApiSuccessResponse[RecoveryRequestOut],
)
def create_recovery_request(
    payload: RecoveryRequestCreate,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    record = service.create_request(
        actor=actor,
        file_id=payload.file_id,
        reason=payload.reason,
        target_key_id=payload.target_key_id,
        context=context,
    )
    return ok(
        message="Recovery request created",
        data=_request_out(record),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{request_id}/approve",
    response_model=ApiSuccessResponse[RecoveryRequestActionResponse],
)
def approve_recovery_request(
    request_id: UUID,
    actor: ReviewerActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    record = service.approve_request(
        actor=actor,
        request_id=request_id,
        context=context,
    )
    return ok(
        message="Recovery request approved",
        data=RecoveryRequestActionResponse(request=_request_out(record), changed=True),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{request_id}/reject",
    response_model=ApiSuccessResponse[RecoveryRequestActionResponse],
)
def reject_recovery_request(
    request_id: UUID,
    payload: RecoveryRejectRequest,
    actor: ReviewerActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    record = service.reject_request(
        actor=actor,
        request_id=request_id,
        rejection_reason=payload.rejection_reason,
        context=context,
    )
    return ok(
        message="Recovery request rejected",
        data=RecoveryRequestActionResponse(request=_request_out(record), changed=True),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{request_id}/cancel",
    response_model=ApiSuccessResponse[RecoveryRequestActionResponse],
)
def cancel_recovery_request(
    request_id: UUID,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    record, changed = service.cancel_request(
        actor=actor,
        request_id=request_id,
        context=context,
    )
    return ok(
        message="Recovery request cancellation processed",
        data=RecoveryRequestActionResponse(request=_request_out(record), changed=changed),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{request_id}/execute",
    response_model=ApiSuccessResponse[RecoveryRequestActionResponse],
)
def execute_recovery_request(
    request_id: UUID,
    payload: RecoveryExecuteRequest,
    actor: ReviewerActorDependency,
    context: RequestContextDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    record, changed = service.execute_request(
        actor=actor,
        request_id=request_id,
        wrapped_file_key=payload.wrapped_key_bytes(),
        recovery_key_id=payload.recovery_key_id,
        target_key_id=payload.target_key_id,
        context=context,
    )
    return ok(
        message="Recovery request execution processed",
        data=RecoveryRequestActionResponse(request=_request_out(record), changed=changed),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get(
    "/{request_id}/execution-package",
    response_model=ApiSuccessResponse[RecoveryExecutionPackageOut],
)
def get_recovery_execution_package(
    request_id: UUID,
    actor: ReviewerActorDependency,
    service: RecoveryServiceDependency,
) -> JSONResponse:
    record = service.get_execution_package(actor=actor, request_id=request_id)
    data = RecoveryExecutionPackageOut(
        request_id=UUID(record.request.request_uuid),
        file_id=UUID(record.file.file_uuid),
        requester_id=UUID(record.requester.user_uuid),
        expires_at=to_api_utc(record.request.expires_at),
        recovery_key=RecoveryExecutionKeyOut(
            key_id=UUID(record.recovery_key.key_uuid),
            algorithm=record.recovery_key.algorithm,
            key_size_bits=record.recovery_key.key_size_bits,
            public_key_pem=record.recovery_key.public_key_pem,
            fingerprint=record.recovery_key.fingerprint,
        ),
        recovery_wrapped_file_key=base64.b64encode(record.source_wrapping.wrapped_file_key).decode(
            "ascii"
        ),
        target_key=RecoveryExecutionKeyOut(
            key_id=UUID(record.target_key.key_uuid),
            algorithm=record.target_key.algorithm,
            key_size_bits=record.target_key.key_size_bits,
            public_key_pem=record.target_key.public_key_pem,
            fingerprint=record.target_key.fingerprint,
        ),
    )
    return ok(
        message="Recovery execution package retrieved",
        data=data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get(
    "/requests",
    response_model=ApiSuccessResponse[RecoveryRequestListResponse],
)
def list_recovery_requests(
    actor: ActorDependency,
    service: RecoveryServiceDependency,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> JSONResponse:
    records, total = service.list_requests(actor=actor, page=page, page_size=page_size)
    data = RecoveryRequestListResponse(
        requests=[_request_out(record) for record in records],
        page=page,
        page_size=page_size,
        total=total,
    )
    return ok(
        message="Recovery requests retrieved",
        data=data,
        headers=AUTH_NO_STORE_HEADERS,
    )
