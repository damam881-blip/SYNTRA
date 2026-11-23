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


def test_ping_endpoint_round_trip(client):
    # create project
    r = client.post("/api/v1/projects", json={"name": "Ping Lab"})
    assert r.status_code == 201
    project_id = r.json()["data"]["project"]["project_id"]
    etag = r.headers["ETag"]

    # add two PCs
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

    # configure IPv4
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

    # connect
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

    # create ping
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
