from app.core.exceptions import (
    AppError,
    ConflictError,
    InternalError,
    NotFoundError,
    UnsupportedError,
    ValidationError,
)


def test_subclass_defaults():
    cases = [
        (ValidationError, "VALIDATION_ERROR", 422),
        (NotFoundError, "NOT_FOUND", 404),
        (ConflictError, "CONFLICT", 409),
        (UnsupportedError, "UNSUPPORTED", 422),
        (InternalError, "INTERNAL_ERROR", 500),
    ]
    for cls, code, status in cases:
        error = cls()
        assert error.code == code
        assert error.http_status == status
        assert isinstance(error, AppError)


def test_to_dict_shape():
    error = NotFoundError("Device missing", details={"device_id": "abc"})

    assert error.to_dict("req-1") == {
        "code": "NOT_FOUND",
        "message": "Device missing",
        "details": {"device_id": "abc"},
        "request_id": "req-1",
    }


def test_code_override_and_details_are_copied():
    source = {"field": "mask"}
    error = ValidationError("bad mask", code="INVALID_SUBNET_MASK", details=source)
    source["field"] = "changed"

    assert error.code == "INVALID_SUBNET_MASK"
    assert error.details == {"field": "mask"}
    assert error.to_dict()["request_id"] is None
