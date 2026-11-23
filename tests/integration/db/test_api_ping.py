from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import api_v1_router
from app.core.error_handlers import register_error_handlers
from app.core.middleware import RequestIDMiddleware
from app.db.base import uuid7
from app.db.session import create_session_factory


@pytest.fixture
def client(clean_engine):
    test_app = FastAPI()
    test_app.state.session_factory = create_session_factory(clean_engine)
    test_app.add_middleware(RequestIDMiddleware)
    register_error_handlers(test_app)
    test_app.include_router(api_v1_router, prefix="/api/v1")
    with TestClient(test_app) as test_client:
        yield test_client


def _prepare_network(client):
    r = client.post("/api/v1/projects", json={"name": "Ping Lab"})
    assert r.status_code == 201
    project_id = r.json()["data"]["project"]["project_id"]
    etag = r.headers["ETag"]

    r = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json={"kind": "PC", "display_name": "PC-A"},
        headers={"If-Match": etag},
    )
    assert r.status_code == 201
    etag = r.headers["ETag"]
    doc = r.json()["data"]
    pc_a = doc["devices"][0]["device_id"]
    iface_a = doc["interfaces"][0]["interface_id"]

    r = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json={"kind": "PC", "display_name": "PC-B"},
        headers={"If-Match": etag},
    )
    assert r.status_code == 201
    etag = r.headers["ETag"]
    doc = r.json()["data"]
    pc_b = doc["devices"][1]["device_id"]
    iface_b = doc["interfaces"][1]["interface_id"]

    r = client.put(
        f"/api/v1/projects/{project_id}/interfaces/{iface_a}/ipv4",
        json={"address": "192.168.10.10", "prefix_length": 24},
        headers={"If-Match": etag},
    )
    assert r.status_code == 200
    etag = r.headers["ETag"]
    r = client.put(
        f"/api/v1/projects/{project_id}/interfaces/{iface_b}/ipv4",
        json={"address": "192.168.10.20", "prefix_length": 24},
        headers={"If-Match": etag},
    )
    assert r.status_code == 200
    etag = r.headers["ETag"]

    r = client.post(
        f"/api/v1/projects/{project_id}/connections",
        json={
            "interface_a_id": iface_a,
            "interface_b_id": iface_b,
            "cable_type": "GENERIC_ETHERNET",
        },
        headers={"If-Match": etag},
    )
    assert r.status_code == 201
    etag = r.headers["ETag"]
    return project_id, etag, pc_a, pc_b


def test_ping_endpoint_round_trip(client):
    project_id, etag, pc_a, pc_b = _prepare_network(client)

    test_id = str(uuid7())
    r = client.post(
        f"/api/v1/projects/{project_id}/ping-tests",
        json={"test_id": test_id, "source_device_id": pc_a, "destination_device_id": pc_b},
        headers={"If-Match": etag},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["data"]["aggregate_outcome"] == "SUCCESS"
    assert body["data"]["statistics"]["replies_received"] == 4

    # get ping
    r = client.get(f"/api/v1/projects/{project_id}/ping-tests/{test_id}")
    assert r.status_code == 200
    assert r.json()["data"]["test_id"] == test_id


def test_ping_retry_is_idempotent_and_returns_200(client):
    project_id, etag, pc_a, pc_b = _prepare_network(client)
    test_id = str(uuid7())
    payload = {
        "test_id": test_id,
        "source_device_id": pc_a,
        "destination_device_id": pc_b,
    }
    first = client.post(
        f"/api/v1/projects/{project_id}/ping-tests",
        json=payload,
        headers={"If-Match": etag},
    )
    assert first.status_code == 201
    assert first.headers["Location"].endswith(f"/ping-tests/{test_id}")
    retry = client.post(
        f"/api/v1/projects/{project_id}/ping-tests",
        json=payload,
        headers={"If-Match": etag},
    )
    assert retry.status_code == 200
    assert retry.json()["data"] == first.json()["data"]


def test_ping_test_id_reuse_conflict(client):
    project_id, etag, pc_a, pc_b = _prepare_network(client)
    test_id = str(uuid7())
    payload = {
        "test_id": test_id,
        "source_device_id": pc_a,
        "destination_device_id": pc_b,
    }
    first = client.post(
        f"/api/v1/projects/{project_id}/ping-tests",
        json=payload,
        headers={"If-Match": etag},
    )
    assert first.status_code == 201
    conflict = client.post(
        f"/api/v1/projects/{project_id}/ping-tests",
        json={**payload, "source_device_id": pc_b},
        headers={"If-Match": etag},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "TEST_ID_REUSE_CONFLICT"
    assert conflict.json()["error"]["request_id"]


def test_ping_unsupported_endpoint_uses_validation_envelope(client):
    project_id, etag, pc_a, pc_b = _prepare_network(client)
    # No router exists in this topology, so use a UUIDv7 not belonging to the project.
    unknown = str(uuid7())
    response = client.post(
        f"/api/v1/projects/{project_id}/ping-tests",
        json={
            "test_id": str(uuid7()),
            "source_device_id": unknown,
            "destination_device_id": pc_b,
        },
        headers={"If-Match": etag},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_persistence_errors_keep_outer_error_envelope(client):
    created = client.post("/api/v1/projects", json={"name": "Error Lab"})
    project_id = created.json()["data"]["project"]["project_id"]
    missing_match = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json={"kind": "PC", "display_name": "PC-A"},
    )
    assert missing_match.status_code == 428
    assert missing_match.json()["error"]["code"] == "PRECONDITION_REQUIRED"
    assert missing_match.json()["error"]["request_id"]

    unknown_project = client.get(f"/api/v1/projects/{uuid7()}")
    assert unknown_project.status_code == 404
    assert unknown_project.json()["error"]["code"] == "NOT_FOUND"
