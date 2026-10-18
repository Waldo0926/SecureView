from collections.abc import Mapping
from typing import Any, Generic, Literal, TypeVar

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

ResponseDataT = TypeVar("ResponseDataT")

AUTH_NO_STORE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


class ApiSuccessResponse(BaseModel, Generic[ResponseDataT]):
    """Typed success envelope used by OpenAPI and response validation."""

    success: Literal[True] = True
    status: Literal["success"] = "success"
    message: str
    data: ResponseDataT
    description: str | None = None
    code: int

    model_config = ConfigDict(extra="forbid")


def _build_response(
    *,
    success: bool,
    status: str,
    message: str,
    data: Any,
    description: str | None,
    code: int,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        headers=headers,
        content=jsonable_encoder(
            {
                "success": success,
                "status": status,
                "message": message,
                "data": data,
                "description": description,
                "code": code,
            }
        ),
    )


class ApiResponse:
    @staticmethod
    def success(
        data: Any = None,
        message: str = "Success",
        description: str | None = None,
        code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        return _build_response(
            success=True,
            status="success",
            message=message,
            data=data,
            description=description,
            code=code,
            headers=headers,
        )

    @staticmethod
    def fail(
        message: str = "Request failed",
        data: Any = None,
        description: str | None = None,
        code: int = 400,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        return _build_response(
            success=False,
            status="fail",
            message=message,
            data=data,
            description=description,
            code=code,
            headers=headers,
        )

    @staticmethod
    def error(
        message: str = "Internal server error",
        data: Any = None,
        description: str | None = None,
        code: int = 500,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        return _build_response(
            success=False,
            status="error",
            message=message,
            data=data,
            description=description,
            code=code,
            headers=headers,
        )


def ok(
    message: str = "Success",
    data: Any = None,
    description: str | None = None,
    code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return ApiResponse.success(
        data=data,
        message=message,
        description=description,
        code=code,
        headers=headers,
    )


def fail(
    message: str = "Request failed",
    data: Any = None,
    description: str | None = None,
    code: int = 400,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return ApiResponse.fail(
        message=message,
        data=data,
        description=description,
        code=code,
        headers=headers,
    )


def error(
    message: str = "Internal server error",
    data: Any = None,
    description: str | None = None,
    code: int = 500,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return ApiResponse.error(
        message=message,
        data=data,
        description=description,
        code=code,
        headers=headers,
    )
