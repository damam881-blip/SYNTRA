"""TASK-07 §14.2 step 5: If-Match revision guard over PostgreSQL (§5.2, D7-02)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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


def _create_project(client):
    response = client.post("/api/v1/projects", json={"name": "Guard Lab"})
    assert response.status_code == 201
    body = response.json()["data"]
    return body["project"]["project_id"], response.headers["ETag"]


def _device_payload(name="PC-01"):
    return {"kind": "PC", "display_name": name}


def test_protected_write_without_if_match_returns_428_and_changes_nothing(client):
    project_id, _ = _create_project(client)
    response = client.post(f"/api/v1/projects/{project_id}/devices", json=_device_payload())
    assert response.status_code == 428
    error = response.json()["error"]
    assert error["code"] == "PRECONDITION_REQUIRED"
    assert error["request_id"] is not None

    opened = client.get(f"/api/v1/projects/{project_id}").json()["data"]
    assert opened["project"]["state_revision"] == 1
    assert opened["devices"] == []


def test_stale_if_match_returns_412_with_current_revisions(client):
    project_id, etag_v1 = _create_project(client)
    created = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json=_device_payload(),
        headers={"If-Match": etag_v1},
    )
    assert created.status_code == 201
    device_id = created.json()["data"]["devices"][0]["device_id"]

    response = client.patch(
        f"/api/v1/projects/{project_id}/devices/{device_id}/name",
        json={"display_name": "PC-STALE"},
        headers={"If-Match": etag_v1},
    )
    assert response.status_code == 412
    error = response.json()["error"]
    assert error["code"] == "STALE_PROJECT_STATE"
    assert error["details"] == {
        "expected_state_revision": 1,
        "current_state_revision": 2,
        "current_simulation_revision": 2,
    }

    opened = client.get(f"/api/v1/projects/{project_id}").json()["data"]
    assert opened["project"]["state_revision"] == 2
    assert opened["devices"][0]["display_name"] == "PC-01"


def test_same_etag_cannot_commit_twice_sequentially(client):
    project_id, etag_v1 = _create_project(client)
    first = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json=_device_payload("PC-A"),
        headers={"If-Match": etag_v1},
    )
    second = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json=_device_payload("PC-B"),
        headers={"If-Match": etag_v1},
    )
    assert first.status_code == 201
    assert second.status_code == 412

    opened = client.get(f"/api/v1/projects/{project_id}").json()["data"]
    assert opened["project"]["state_revision"] == 2
    assert [device["display_name"] for device in opened["devices"]] == ["PC-A"]


def test_concurrent_writes_with_same_etag_one_commits_one_gets_412(client):
    project_id, etag_v1 = _create_project(client)

    def submit(name):
        return client.post(
            f"/api/v1/projects/{project_id}/devices",
            json=_device_payload(name),
            headers={"If-Match": etag_v1},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ["PC-A", "PC-B"]))

    assert sorted(response.status_code for response in responses) == [201, 412]
    opened = client.get(f"/api/v1/projects/{project_id}").json()["data"]
    assert opened["project"]["state_revision"] == 2
    assert len(opened["devices"]) == 1


def test_checkpoint_save_requires_if_match(client):
    project_id, _ = _create_project(client)
    response = client.post(f"/api/v1/projects/{project_id}/checkpoints", json={"label": "x"})
    assert response.status_code == 428
    assert response.json()["error"]["code"] == "PRECONDITION_REQUIRED"


def test_delete_project_requires_if_match(client):
    project_id, _ = _create_project(client)
    response = client.request(
        "DELETE",
        f"/api/v1/projects/{project_id}",
        json={"confirm_name": "Guard Lab"},
    )
    assert response.status_code == 428
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 200


def test_malformed_if_match_returns_412_with_sentinel_expected_revision(client):
    project_id, _ = _create_project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json=_device_payload(),
        headers={"If-Match": "not-an-etag"},
    )
    assert response.status_code == 412
    details = response.json()["error"]["details"]
    assert details["expected_state_revision"] == 0
    assert details["current_state_revision"] == 1


def test_reads_and_project_creation_do_not_require_if_match(client):
    project_id, etag = _create_project(client)
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 200
    response = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json=_device_payload(),
        headers={"If-Match": etag},
    )
    assert response.status_code == 201
