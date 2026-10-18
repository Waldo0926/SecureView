from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_actor, get_request_context, get_sharing_service
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiSuccessResponse, ok
from app.core.time import to_api_utc
from app.domain.auth import ActorContext, RequestContext
from app.schemas.share_schema import (
    RevokeAccessRequest,
    RevokeAccessResponse,
    SharedUserOut,
    SharedUsersResponse,
    ShareFileRequest,
    ShareFileResponse,
)
from app.services.sharing_service import SharingService

router = APIRouter()

ActorDependency = Annotated[ActorContext, Depends(get_current_actor)]
SharingServiceDependency = Annotated[SharingService, Depends(get_sharing_service)]
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


@router.post(
    "/{file_id}/share",
    response_model=ApiSuccessResponse[ShareFileResponse],
)
def share_file(
    file_id: UUID,
    payload: ShareFileRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: SharingServiceDependency,
) -> JSONResponse:
    created, share_status = service.share(
        actor=actor,
        file_id=file_id,
        target_user_id=payload.target_user_id,
        target_key_id=payload.target_key_id,
        wrapped_file_key=payload.wrapped_key_bytes(),
        can_download=payload.can_download,
        can_share=payload.can_share,
        context=context,
    )
    data = ShareFileResponse(
        file_id=file_id,
        target_user_id=payload.target_user_id,
        target_key_id=payload.target_key_id,
        status=share_status,
        created=created,
    )
    return ok(message="File shared", data=data, headers=AUTH_NO_STORE_HEADERS)


@router.get(
    "/{file_id}/shared-users",
    response_model=ApiSuccessResponse[SharedUsersResponse],
)
def shared_users(
    file_id: UUID,
    actor: ActorDependency,
    service: SharingServiceDependency,
) -> JSONResponse:
    file, rows = service.list_shared_users(actor=actor, file_id=file_id)
    users = [
        SharedUserOut(
            user_id=UUID(user.user_uuid),
            username=user.username,
            key_id=UUID(key.key_uuid),
            can_download=grant.can_download,
            can_share=grant.can_share,
            is_owner=user.id == file.owner_id,
            granted_at=to_api_utc(grant.created_at),
        )
        for grant, user, key in rows
    ]
    return ok(
        message="Shared users retrieved",
        data=SharedUsersResponse(file_id=file_id, users=users),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{file_id}/revoke",
    response_model=ApiSuccessResponse[RevokeAccessResponse],
)
def revoke_access(
    file_id: UUID,
    payload: RevokeAccessRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: SharingServiceDependency,
) -> JSONResponse:
    revoked = service.revoke(
        actor=actor,
        file_id=file_id,
        target_user_id=payload.target_user_id,
        context=context,
    )
    data = RevokeAccessResponse(
        file_id=file_id,
        target_user_id=payload.target_user_id,
        revoked=revoked,
    )
    return ok(message="Access revocation processed", data=data, headers=AUTH_NO_STORE_HEADERS)
