from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.api.dependencies import (
    get_current_actor,
    get_file_service,
    get_request_context,
)
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiResponse, ApiSuccessResponse
from app.domain.auth import ActorContext, RequestContext
from app.domain.errors import InputError
from app.schemas.file_schema import (
    CiphertextPreviewOut,
    FileDeleteOut,
    FileFolderDeleteOut,
    FileFolderListOut,
    FileFolderOut,
    FileListOut,
    FileMoveIn,
    FileMoveOut,
    FileOut,
    FileUploadMetadata,
    FolderNameIn,
    IntegrityCheckOut,
)
from app.services.file_service import FileService

router = APIRouter()


def _metadata_from_json(raw_metadata: str) -> FileUploadMetadata:
    if len(raw_metadata.encode("utf-8")) > 100_000:
        raise InputError("metadata exceeds the 100000-byte size limit")
    try:
        return FileUploadMetadata.model_validate_json(raw_metadata)
    except ValidationError as exc:
        errors = []
        for error in exc.errors(include_url=False, include_input=False):
            item = dict(error)
            item["loc"] = ("body", "metadata", *error.get("loc", ()))
            errors.append(item)
        raise RequestValidationError(errors) from exc


@router.post(
    "/upload",
    response_model=ApiSuccessResponse[FileOut],
    status_code=201,
)
async def upload_file(
    file: Annotated[UploadFile, File(description="Client-encrypted ciphertext")],
    metadata: Annotated[str, Form(description="JSON FileUploadMetadata envelope")],
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    context: Annotated[RequestContext, Depends(get_request_context)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    result = await service.upload(
        actor=actor,
        metadata=_metadata_from_json(metadata),
        ciphertext=file,
        context=context,
    )
    return ApiResponse.success(
        data=result,
        message="Encrypted file uploaded",
        code=201,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get("", response_model=ApiSuccessResponse[FileListOut])
def list_files(
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    search: Annotated[
        str | None,
        Query(
            max_length=255,
            description="Case-insensitive substring of the original filename",
        ),
    ] = None,
    folder_id: Annotated[
        UUID | None,
        Query(description="Return files the caller put in this folder of theirs"),
    ] = None,
    unfiled: Annotated[
        bool,
        Query(description="Return only files the caller has not put in a folder"),
    ] = False,
    scope: Annotated[
        Literal["all", "mine", "shared"],
        Query(description="All files, only the caller's own, or only files shared with them"),
    ] = "all",
) -> JSONResponse:
    if folder_id is not None and unfiled:
        raise InputError("folder_id and unfiled cannot be used together")
    result = service.list_files(
        actor=actor,
        page=page,
        page_size=page_size,
        search=search,
        folder_id=folder_id,
        unfiled=unfiled,
        scope=scope,
    )
    return ApiResponse.success(
        data=result,
        message="Files retrieved",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get("/folders", response_model=ApiSuccessResponse[FileFolderListOut])
def list_folders(
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    return ApiResponse.success(
        data=service.list_folders(actor=actor),
        message="File folders retrieved",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/folders", response_model=ApiSuccessResponse[FileFolderOut], status_code=201)
def create_folder(
    body: FolderNameIn,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    return ApiResponse.success(
        data=service.create_folder(actor=actor, name=body.name),
        message="File folder created",
        code=201,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/folders/{folder_id}/rename", response_model=ApiSuccessResponse[FileFolderOut])
def rename_folder(
    folder_id: UUID,
    body: FolderNameIn,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    return ApiResponse.success(
        data=service.rename_folder(actor=actor, folder_id=folder_id, name=body.name),
        message="File folder renamed",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/folders/{folder_id}/delete", response_model=ApiSuccessResponse[FileFolderDeleteOut])
def delete_folder(
    folder_id: UUID,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    return ApiResponse.success(
        data=service.delete_folder(actor=actor, folder_id=folder_id),
        message="File folder deleted; its files are now unfiled",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/{file_id}/move", response_model=ApiSuccessResponse[FileMoveOut])
def move_file(
    file_id: UUID,
    body: FileMoveIn,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    return ApiResponse.success(
        data=service.move_file(actor=actor, file_id=file_id, folder_id=body.folder_id),
        message="File moved",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get("/{file_id}", response_model=ApiSuccessResponse[FileOut])
def get_file(
    file_id: UUID,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    result = service.get_file(actor=actor, file_id=file_id)
    return ApiResponse.success(
        data=result,
        message="File metadata retrieved",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{file_id}/download",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "Verified client-encrypted ciphertext",
        }
    },
)
def download_file(
    file_id: UUID,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    context: Annotated[RequestContext, Depends(get_request_context)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> StreamingResponse:
    result = service.download(actor=actor, file_id=file_id, context=context)
    download_name = f"{result.original_filename}.ciphertext"
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", download_name).strip("._")
    fallback = (fallback or "encrypted-file.ciphertext")[:150]
    content_disposition = (
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(download_name, safe='')}"
    )
    return StreamingResponse(
        result.verified_ciphertext.iter_chunks(),
        media_type="application/octet-stream",
        headers={
            **AUTH_NO_STORE_HEADERS,
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Content-Disposition": content_disposition,
            "Content-Length": str(result.ciphertext_size),
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.post(
    "/{file_id}/ciphertext-preview",
    response_model=ApiSuccessResponse[CiphertextPreviewOut],
)
def ciphertext_preview(
    file_id: UUID,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    context: Annotated[RequestContext, Depends(get_request_context)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    result = service.ciphertext_preview(actor=actor, file_id=file_id, context=context)
    return ApiResponse.success(
        data=result,
        message="Ciphertext preview",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/{file_id}/delete", response_model=ApiSuccessResponse[FileDeleteOut])
def delete_file(
    file_id: UUID,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    context: Annotated[RequestContext, Depends(get_request_context)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    result = service.delete(actor=actor, file_id=file_id, context=context)
    return ApiResponse.success(
        data=result,
        message="File deleted",
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/{file_id}/integrity-check",
    response_model=ApiSuccessResponse[IntegrityCheckOut],
)
def integrity_check(
    file_id: UUID,
    actor: Annotated[ActorContext, Depends(get_current_actor)],
    context: Annotated[RequestContext, Depends(get_request_context)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> JSONResponse:
    result = service.integrity_check(actor=actor, file_id=file_id, context=context)
    return ApiResponse.success(
        data=result,
        message="Ciphertext integrity checked",
        headers=AUTH_NO_STORE_HEADERS,
    )
