from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_real_app_adds_request_id_header():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_real_app_uses_error_envelope_for_unknown_route():
    response = client.get("/does-not-exist", headers={"X-Request-ID": "wiring-1"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Not Found",
            "details": {},
            "request_id": "wiring-1",
        }
    }
    assert response.headers["X-Request-ID"] == "wiring-1"
