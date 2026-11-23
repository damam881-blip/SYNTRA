"""TASK-07 §14.2 step 4: /api/v1 route mounting and the position PATCH DTO."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.schemas import DevicePositionRequest
from app.main import app

EXPECTED_ROUTES = {
    ("POST", "/api/v1/projects"),
    ("GET", "/api/v1/projects/{project_id}"),
    ("DELETE", "/api/v1/projects/{project_id}"),
    ("POST", "/api/v1/projects/{project_id}/checkpoints"),
    ("POST", "/api/v1/projects/{project_id}/devices"),
    ("PATCH", "/api/v1/projects/{project_id}/devices/{device_id}/name"),
    ("PATCH", "/api/v1/projects/{project_id}/devices/{device_id}/position"),
    ("PATCH", "/api/v1/projects/{project_id}/devices/{device_id}/rotation"),
    ("DELETE", "/api/v1/projects/{project_id}/devices/{device_id}"),
    ("PUT", "/api/v1/projects/{project_id}/devices/{device_id}/default-gateway"),
    ("DELETE", "/api/v1/projects/{project_id}/devices/{device_id}/default-gateway"),
    ("PATCH", "/api/v1/projects/{project_id}/interfaces/{interface_id}/admin-state"),
    ("PUT", "/api/v1/projects/{project_id}/interfaces/{interface_id}/ipv4"),
    ("DELETE", "/api/v1/projects/{project_id}/interfaces/{interface_id}/ipv4"),
    ("POST", "/api/v1/projects/{project_id}/connections"),
    ("DELETE", "/api/v1/projects/{project_id}/connections/{connection_id}"),
    ("POST", "/api/v1/projects/{project_id}/static-routes"),
    ("PATCH", "/api/v1/projects/{project_id}/static-routes/{route_id}"),
    ("DELETE", "/api/v1/projects/{project_id}/static-routes/{route_id}"),
}


QUERY_ROUTES = {
    ("GET", "/api/v1/projects"),
    ("GET", "/api/v1/projects/{project_id}/revisions"),
    ("GET", "/api/v1/projects/{project_id}/checkpoints"),
    ("GET", "/api/v1/projects/{project_id}/devices"),
    ("GET", "/api/v1/projects/{project_id}/devices/{device_id}"),
    ("GET", "/api/v1/projects/{project_id}/interfaces"),
    ("GET", "/api/v1/projects/{project_id}/connections"),
    ("GET", "/api/v1/projects/{project_id}/static-routes"),
}

PING_ROUTES = {
    ("POST", "/api/v1/projects/{project_id}/ping-tests"),
    ("GET", "/api/v1/projects/{project_id}/ping-tests/{test_id}"),
}


def _openapi_operations() -> dict[tuple[str, str], str]:
    """Resolve mounted operations through OpenAPI.

    FastAPI 0.158 keeps included routers lazy (``_IncludedRouter``), so
    ``app.routes`` is not a flat route list; the generated OpenAPI document
    is the authoritative view of the mounted surface.
    """
    operations: dict[tuple[str, str], str] = {}
    for path, item in app.openapi()["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                operations[(method.upper(), path)] = operation["operationId"]
    return operations


def test_all_step4_routes_are_mounted_under_api_v1():
    assert EXPECTED_ROUTES <= set(_openapi_operations())


def test_step6_query_routes_are_mounted():
    assert QUERY_ROUTES <= set(_openapi_operations())


def test_step7_ping_routes_are_mounted():
    assert PING_ROUTES <= set(_openapi_operations())


def test_health_endpoint_is_preserved():
    assert ("GET", "/health") in _openapi_operations()


def test_operation_ids_are_unique_and_named():
    operations = {
        key: operation_id
        for key, operation_id in _openapi_operations().items()
        if key[1].startswith("/api/v1")
    }
    assert len(operations) == len(EXPECTED_ROUTES) + len(QUERY_ROUTES) + len(PING_ROUTES)
    operation_ids = list(operations.values())
    assert len(set(operation_ids)) == len(operation_ids)
    assert "createProject" in operation_ids
    assert "openProject" in operation_ids
    assert "deleteProject" in operation_ids
    assert "listProjects" in operation_ids
    assert "getDevice" in operation_ids


# --- DevicePositionRequest (§7.2: PATCH position body is {position:{x,y,z}}) ---


def test_position_request_requires_the_position_wrapper():
    with pytest.raises(ValidationError):
        DevicePositionRequest.model_validate({"x": 1.0, "y": 2.0, "z": 3.0})


def test_position_request_accepts_canonical_body():
    parsed = DevicePositionRequest.model_validate({"position": {"x": 1.0, "y": 2.0, "z": 3.0}})
    assert (parsed.position.x, parsed.position.y, parsed.position.z) == (1.0, 2.0, 3.0)


def test_position_request_forbids_extra_fields_at_both_levels():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DevicePositionRequest.model_validate(
            {"position": {"x": 0, "y": 0, "z": 0}, "rotation_y_degrees": 0}
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DevicePositionRequest.model_validate({"position": {"x": 0, "y": 0, "z": 0, "w": 1}})
