"""TASK-07 §14.2 steps 4–5: /api/v1 routers over PostgreSQL-backed services.

Scope: mounting, status codes, canonical mutation responses, ETag values,
receipts, request-validation 422 and the If-Match revision guard. Query
projections (step 6), Ping (step 7) and persistence-error mapping (step 8)
are deliberately not asserted here.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import api_v1_router
from app.core.error_handlers import register_error_handlers
from app.core.middleware import RequestIDMiddleware
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


def _create_project(client, name="API Lab"):
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201
    body = response.json()
    project_id = body["data"]["project"]["project_id"]
    return project_id, body, response.headers["ETag"]


def _add_device(client, project_id, etag, kind="PC", display_name="PC-01"):
    response = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json={"kind": kind, "display_name": display_name},
        headers={"If-Match": etag},
    )
    assert response.status_code == 201
    return response.json()["data"], response.headers["ETag"]


def _etag(project_id, revision):
    return f'"p-{project_id}-s{revision}"'


# --- projects ---------------------------------------------------------------


def test_create_project_returns_201_canonical_document_and_etag(client):
    project_id, body, etag = _create_project(client)
    assert body["data"]["schema_version"] == "1.0.0"
    assert body["data"]["project"]["state_revision"] == 1
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["request_id"] is not None
    assert etag == _etag(project_id, 1)


def test_open_project_returns_200_with_matching_etag(client):
    project_id, created, _ = _create_project(client)
    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200
    assert response.headers["ETag"] == _etag(project_id, 1)
    assert response.json()["data"] == created["data"]


def test_request_id_is_echoed_into_meta_and_header(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": "Traced Lab"},
        headers={"X-Request-ID": "unity-request-000042"},
    )
    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "unity-request-000042"
    assert response.json()["meta"]["request_id"] == "unity-request-000042"


def test_delete_project_returns_tombstone_receipt_without_etag(client):
    project_id, _, etag = _create_project(client, name="Doomed Lab")
    response = client.request(
        "DELETE",
        f"/api/v1/projects/{project_id}",
        json={"confirm_name": "Doomed Lab"},
        headers={"If-Match": etag},
    )
    assert response.status_code == 200
    receipt = response.json()["data"]
    assert receipt["project_id"] == project_id
    assert receipt["project_name"] == "Doomed Lab"
    assert receipt["last_state_revision"] == 1
    assert receipt["last_simulation_revision"] == 1
    assert receipt["deleted_at"].endswith("Z")
    assert "ETag" not in response.headers


def test_checkpoint_save_returns_receipt_and_keeps_etag(client):
    project_id, _, etag = _create_project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/checkpoints",
        json={"label": "before edits"},
        headers={"If-Match": etag},
    )
    assert response.status_code == 201
    receipt = response.json()["data"]
    assert receipt["revision"] == 1
    assert receipt["label"] == "before edits"
    assert response.headers["ETag"] == etag

    opened = client.get(f"/api/v1/projects/{project_id}").json()["data"]
    assert opened["project"]["state_revision"] == 1
    assert opened["checkpoints"][0]["checkpoint_id"] == receipt["checkpoint_id"]


# --- devices and gateway ------------------------------------------------------


def test_device_lifecycle_advances_revision_once_per_mutation(client):
    project_id, _, etag = _create_project(client)
    document, etag = _add_device(client, project_id, etag)
    assert document["project"]["state_revision"] == 2
    device = document["devices"][0]
    device_id = device["device_id"]
    assert len(document["interfaces"]) >= 1

    base = f"/api/v1/projects/{project_id}/devices/{device_id}"
    steps = [
        ("PATCH", f"{base}/name", {"display_name": "PC-RENAMED"}, 3),
        ("PATCH", f"{base}/position", {"position": {"x": 1.5, "y": 0.0, "z": -2.0}}, 4),
        ("PATCH", f"{base}/rotation", {"rotation_y_degrees": 90.0}, 5),
        ("PUT", f"{base}/default-gateway", {"gateway_ipv4": "192.168.10.1"}, 6),
        ("DELETE", f"{base}/default-gateway", None, 7),
        ("DELETE", base, None, 8),
    ]
    for method, path, payload, revision in steps:
        response = client.request(method, path, json=payload, headers={"If-Match": etag})
        assert response.status_code == 200, (method, path, response.text)
        etag = response.headers["ETag"]
        assert etag == _etag(project_id, revision)
        assert response.json()["data"]["project"]["state_revision"] == revision

    final = response.json()["data"]
    assert final["devices"] == []
    assert final["interfaces"] == []


def test_device_position_patch_requires_wrapper(client):
    project_id, _, etag = _create_project(client)
    document, etag = _add_device(client, project_id, etag)
    device_id = document["devices"][0]["device_id"]
    response = client.patch(
        f"/api/v1/projects/{project_id}/devices/{device_id}/position",
        json={"x": 1.0, "y": 0.0, "z": 0.0},
        headers={"If-Match": etag},
    )
    assert response.status_code == 422


# --- interfaces ---------------------------------------------------------------


def test_interface_configuration_lifecycle(client):
    project_id, _, etag = _create_project(client)
    document, etag = _add_device(client, project_id, etag)
    interface_id = document["interfaces"][0]["interface_id"]
    base = f"/api/v1/projects/{project_id}/interfaces/{interface_id}"

    response = client.patch(
        f"{base}/admin-state", json={"admin_state": "DISABLED"}, headers={"If-Match": etag}
    )
    assert response.status_code == 200
    etag = response.headers["ETag"]
    assert response.json()["data"]["interfaces"][0]["admin_state"] == "DISABLED"

    response = client.put(
        f"{base}/ipv4",
        json={"address": "192.168.10.10", "prefix_length": 24},
        headers={"If-Match": etag},
    )
    assert response.status_code == 200
    etag = response.headers["ETag"]
    interface = response.json()["data"]["interfaces"][0]
    assert interface["ipv4"] == {"address": "192.168.10.10", "prefix_length": 24}

    response = client.delete(f"{base}/ipv4", headers={"If-Match": etag})
    assert response.status_code == 200
    interface = response.json()["data"]["interfaces"][0]
    assert "ipv4" not in interface
    assert response.json()["data"]["project"]["state_revision"] == 5


# --- connections ---------------------------------------------------------------


def test_connection_lifecycle(client):
    project_id, _, etag = _create_project(client)
    _, etag = _add_device(client, project_id, etag, display_name="PC-A")
    document, etag = _add_device(client, project_id, etag, display_name="PC-B")
    interfaces = document["interfaces"]
    assert len(interfaces) == 2

    response = client.post(
        f"/api/v1/projects/{project_id}/connections",
        json={
            "interface_a_id": interfaces[0]["interface_id"],
            "interface_b_id": interfaces[1]["interface_id"],
            "cable_type": "GENERIC_ETHERNET",
        },
        headers={"If-Match": etag},
    )
    assert response.status_code == 201
    etag = response.headers["ETag"]
    document = response.json()["data"]
    assert len(document["connections"]) == 1
    connection_id = document["connections"][0]["connection_id"]

    response = client.delete(
        f"/api/v1/projects/{project_id}/connections/{connection_id}",
        headers={"If-Match": etag},
    )
    assert response.status_code == 200
    assert response.json()["data"]["connections"] == []


# --- static routes ---------------------------------------------------------------


def test_static_route_lifecycle(client):
    project_id, _, etag = _create_project(client)
    document, etag = _add_device(client, project_id, etag, kind="ROUTER", display_name="R1")
    router_id = document["devices"][0]["device_id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/static-routes",
        json={
            "router_device_id": router_id,
            "destination_network": "192.168.20.0",
            "prefix_length": 24,
            "next_hop_ipv4": "192.168.10.2",
        },
        headers={"If-Match": etag},
    )
    assert response.status_code == 201
    etag = response.headers["ETag"]
    document = response.json()["data"]
    route = document["static_routes"][0]
    route_id = route["route_id"]

    response = client.patch(
        f"/api/v1/projects/{project_id}/static-routes/{route_id}",
        json={"next_hop_ipv4": "192.168.10.3"},
        headers={"If-Match": etag},
    )
    assert response.status_code == 200
    etag = response.headers["ETag"]
    assert response.json()["data"]["static_routes"][0]["next_hop_ipv4"] == "192.168.10.3"

    response = client.delete(
        f"/api/v1/projects/{project_id}/static-routes/{route_id}",
        headers={"If-Match": etag},
    )
    assert response.status_code == 200
    assert response.json()["data"]["static_routes"] == []


# --- request validation keeps the existing outer error envelope ----------------


def test_extra_field_returns_422_error_envelope(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": "Lab", "surprise": 1},
        headers={"X-Request-ID": "unity-request-000042"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"] == "unity-request-000042"
    assert error["details"]["errors"][0]["type"] == "extra_forbidden"


def test_non_uuid7_path_id_returns_422(client):
    response = client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_empty_route_patch_returns_422(client):
    project_id, _, etag = _create_project(client)
    document, etag = _add_device(client, project_id, etag, kind="ROUTER", display_name="R1")
    router_id = document["devices"][0]["device_id"]
    created = client.post(
        f"/api/v1/projects/{project_id}/static-routes",
        json={
            "router_device_id": router_id,
            "destination_network": "0.0.0.0",
            "prefix_length": 0,
            "next_hop_ipv4": "192.168.10.2",
        },
        headers={"If-Match": etag},
    ).json()["data"]
    route_id = created["static_routes"][0]["route_id"]
    etag = _etag(project_id, created["project"]["state_revision"])
    response = client.patch(
        f"/api/v1/projects/{project_id}/static-routes/{route_id}",
        json={},
        headers={"If-Match": etag},
    )
    assert response.status_code == 422
