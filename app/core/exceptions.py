from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    """Base class for structural/input/boundary errors (T2-05).

    Simulation outcomes (a failed Ping) are NOT errors and must never use this.
    http_status values are PROPOSED defaults; final mapping belongs to TASK-07.
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    default_message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = dict(details) if details else {}
        super().__init__(self.message)

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "request_id": request_id,
        }


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 422
    default_message = "Validation failed"


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "Resource not found"


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409
    default_message = "Request conflicts with current state"


class UnsupportedError(AppError):
    code = "UNSUPPORTED"
    http_status = 422
    default_message = "Operation is not supported in V1"


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    http_status = 500
    default_message = "Internal server error"
