import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError, InternalError
from app.core.middleware import REQUEST_ID_HEADER
from app.db.errors import (
    ContractValidationError,
    DeletionConfirmationError,
    IntegrityConflictError,
    PreconditionConflictError,
    ProjectNotFoundError,
)

logger = logging.getLogger("network_simulator")

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(body, status_code=status_code, headers=response_headers)


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _envelope(
        request,
        status_code=exc.http_status,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def handle_project_not_found(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProjectNotFoundError)
    return _envelope(request, status_code=404, code="NOT_FOUND", message=str(exc))


async def handle_deletion_confirmation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DeletionConfirmationError)
    return _envelope(request, status_code=422, code="VALIDATION_ERROR", message=str(exc))


async def handle_precondition_conflict(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PreconditionConflictError)
    return _envelope(request, status_code=409, code="PRECONDITION_CONFLICT", message=str(exc))


async def handle_integrity_conflict(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IntegrityConflictError)
    return _envelope(request, status_code=409, code="INTEGRITY_CONFLICT", message=str(exc))


async def handle_contract_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ContractValidationError)
    return _envelope(request, status_code=422, code="CONTRACT_VALIDATION_ERROR", message=str(exc))


async def handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return _envelope(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": errors},
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return _envelope(
        request,
        status_code=exc.status_code,
        code=_HTTP_CODES.get(exc.status_code, "HTTP_ERROR"),
        message=str(exc.detail),
        headers=dict(exc.headers) if exc.headers else None,
    )


async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception request_id=%s", _request_id(request), exc_info=exc)
    internal = InternalError()
    return _envelope(
        request,
        status_code=internal.http_status,
        code=internal.code,
        message=internal.message,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(ProjectNotFoundError, handle_project_not_found)
    app.add_exception_handler(DeletionConfirmationError, handle_deletion_confirmation)
    app.add_exception_handler(PreconditionConflictError, handle_precondition_conflict)
    app.add_exception_handler(IntegrityConflictError, handle_integrity_conflict)
    app.add_exception_handler(ContractValidationError, handle_contract_validation)
    app.add_exception_handler(RequestValidationError, handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected)
