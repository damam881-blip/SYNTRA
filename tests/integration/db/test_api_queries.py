"""TASK-07 §14.2 step 6: query projections over PostgreSQL."""

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


def _create_project(client, name):
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201
    body = response.json()["data"]
    return body["project"]["project_id"], response.headers["ETag"]


def _add_device(client, project_id, etag, kind="PC", display_name="PC-01"):
    response = client.post(
        f"/api/v1/projects/{project_id}/devices",
        json={"kind": kind, "display_name": display_name},
        headers={"If-Match": etag},
    )
    assert response.status_code == 201
    return response.json()["data"], response.headers["ETag"]


def _populated_project(client):
    project_id, etag = _create_project(client, "Query Lab")
    document, etag = _add_device(client, project_id, etag, display_name="PC-A")
    document, etag = _add_device(client, project_id, etag, display_name="PC-B")
    document, etag = _add_device(client, project_id, etag, kind="ROUTER", display_name="R1")
    interfaces = document["interfaces"]
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
    router_id = document["devices"][2]["device_id"]
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
    return project_id


# --- project list -------------------------------------------------------------


def test_list_projects_empty(client):
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_list_projects_returns_summaries_without_child_collections(client):
    project_id, _ = _create_project(client, "Summary Lab")
    _populated_project(client)
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    summaries = response.json()["data"]
    assert len(summaries) == 2
    allowed = {
        "project_id",
        "name",
        "description",
        "state_revision",
        "simulation_revision",
        "created_at",
        "updated_at",
    }
    for summary in summaries:
        assert set(summary) <= allowed
        assert "devices" not in summary
    assert {summary["name"] for summary in summaries} == {"Summary Lab", "Query Lab"}
    assert project_id in {summary["project_id"] for summary in summaries}


def test_list_projects_pagination_is_bounded_and_stable(client):
    names = ["Page-A", "Page-B", "Page-C"]
    for name in names:
        _create_project(client, name)

    first = client.get("/api/v1/projects", params={"limit": 2, "offset": 0}).json()["data"]
    second = client.get("/api/v1/projects", params={"limit": 2, "offset": 2}).json()["data"]
    assert [summary["name"] for summary in first] == ["Page-A", "Page-B"]
    assert [summary["name"] for summary in second] == ["Page-C"]

    again = client.get("/api/v1/projects", params={"limit": 2, "offset": 0}).json()["data"]
    assert again == first


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_projects_rejects_out_of_range_pagination(client, params):
    response = client.get("/api/v1/projects", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- child collections ----------------------------------------------------------


def test_collection_projections_match_the_canonical_document(client):
    project_id = _populated_project(client)
    opened = client.get(f"/api/v1/projects/{project_id}")
    document = opened.json()["data"]
    etag = opened.headers["ETag"]

    for key in ("devices", "interfaces", "connections", "static_routes", "revisions"):
        segment = key.replace("_", "-")
        response = client.get(f"/api/v1/projects/{project_id}/{segment}")
        assert response.status_code == 200
        assert response.headers["ETag"] == etag
        assert response.json()["data"] == document[key]
        assert response.json()["meta"]["api_version"] == "v1"


def test_revisions_are_the_full_ordered_array(client):
    project_id = _populated_project(client)
    response = client.get(f"/api/v1/projects/{project_id}/revisions")
    revisions = response.json()["data"]
    # create + 3 devices + connection + route = 6 committed revisions.
    assert [revision["revision"] for revision in revisions] == [1, 2, 3, 4, 5, 6]


def test_checkpoints_list_is_empty_until_saved(client):
    project_id, etag = _create_project(client, "Checkpoint Lab")
    response = client.get(f"/api/v1/projects/{project_id}/checkpoints")
    assert response.status_code == 200
    assert response.json()["data"] == []

    saved = client.post(
        f"/api/v1/projects/{project_id}/checkpoints",
        json={"label": "marker"},
        headers={"If-Match": etag},
    )
    assert saved.status_code == 201
    listed = client.get(f"/api/v1/projects/{project_id}/checkpoints").json()["data"]
    assert len(listed) == 1
    assert listed[0]["checkpoint_id"] == saved.json()["data"]["checkpoint_id"]


# --- single device lookup ---------------------------------------------------------


def test_get_device_returns_the_canonical_device_object(client):
    project_id = _populated_project(client)
    opened = client.get(f"/api/v1/projects/{project_id}")
    device = opened.json()["data"]["devices"][0]
    response = client.get(f"/api/v1/projects/{project_id}/devices/{device['device_id']}")
    assert response.status_code == 200
    assert response.headers["ETag"] == opened.headers["ETag"]
    assert response.json()["data"] == device


def test_get_unknown_device_returns_404_without_leaking_other_projects(client):
    project_id = _populated_project(client)
    response = client.get(f"/api/v1/projects/{project_id}/devices/{uuid7()}")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] is not None
