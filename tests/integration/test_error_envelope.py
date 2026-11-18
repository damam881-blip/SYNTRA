import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.error_handlers import register_error_handlers
from app.core.exceptions import ConflictError, NotFoundError
from app.core.middleware import RequestIDMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/not-found")
    def not_found() -> None:
        raise NotFoundError("Device not found", details={"device_id": "d1"})

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/items")
    def items(n: int) -> dict[str, int]:
        return {"n": n}

    return app


client = TestClient(build_app(), raise_server_exceptions=False)


def test_request_id_is_generated():
    response = client.get("/ok")

    request_id = response.headers["X-Request-ID"]
    assert str(uuid.UUID(request_id)) == request_id


def test_safe_incoming_request_id_is_reused():
    response = client.get("/ok", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_unsafe_incoming_request_id_is_replaced():
    response = client.get("/ok", headers={"X-Request-ID": "bad id with spaces"})

    assert response.headers["X-Request-ID"] != "bad id with spaces"


def test_app_error_envelope():
    response = client.get("/not-found", headers={"X-Request-ID": "req-9"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Device not found",
            "details": {"device_id": "d1"},
            "request_id": "req-9",
        }
    }
    assert response.headers["X-Request-ID"] == "req-9"


def test_conflict_status():
    response = client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_request_validation_envelope():
    response = client.get("/items", params={"n": "abc"})

    body = response.json()["error"]
    assert response.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["loc"] == ["query", "n"]
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_unknown_route_uses_envelope():
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_method_not_allowed_uses_envelope():
    response = client.post("/ok")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unexpected_error_is_hidden_and_has_request_id():
    response = client.get("/boom")

    body = response.json()["error"]
    assert response.status_code == 500
    assert body["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text
    assert body["request_id"] == response.headers["X-Request-ID"]
