"""Unit checks for the TASK-07 revision guard (§5.2, step 5)."""

from __future__ import annotations

import pytest

from app.api.v1.revision import (
    PreconditionRequiredError,
    StaleProjectStateError,
    _expected_revision,
)
from app.main import app


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('"p-019a5000-0000-7000-8000-000000000001-s12"', 12),
        ('"p-019a5000-0000-7000-8000-000000000001-s1"', 1),
        ('"p-019a5000-0000-7000-8000-000000000001-s0"', 0),
        ("not-an-etag", 0),
        ('W/"p-019a5000-0000-7000-8000-000000000001-s12"', 12),
        ("*", 0),
        ("", 0),
    ],
)
def test_expected_revision_parses_the_suffix_or_sentinels_zero(header, expected):
    assert _expected_revision(header) == expected


def test_guard_errors_carry_the_contract_status_and_code():
    missing = PreconditionRequiredError()
    assert (missing.http_status, missing.code) == (428, "PRECONDITION_REQUIRED")
    stale = StaleProjectStateError(details={"current_state_revision": 2})
    assert (stale.http_status, stale.code) == (412, "STALE_PROJECT_STATE")
    assert stale.details == {"current_state_revision": 2}


def test_protected_operations_declare_if_match_in_openapi():
    paths = app.openapi()["paths"]
    protected = [
        ("/projects/{project_id}", "delete"),
        ("/projects/{project_id}/checkpoints", "post"),
        ("/projects/{project_id}/devices", "post"),
        ("/projects/{project_id}/devices/{device_id}/name", "patch"),
        ("/projects/{project_id}/devices/{device_id}/position", "patch"),
        ("/projects/{project_id}/devices/{device_id}/rotation", "patch"),
        ("/projects/{project_id}/devices/{device_id}", "delete"),
        ("/projects/{project_id}/devices/{device_id}/default-gateway", "put"),
        ("/projects/{project_id}/devices/{device_id}/default-gateway", "delete"),
        ("/projects/{project_id}/interfaces/{interface_id}/admin-state", "patch"),
        ("/projects/{project_id}/interfaces/{interface_id}/ipv4", "put"),
        ("/projects/{project_id}/interfaces/{interface_id}/ipv4", "delete"),
        ("/projects/{project_id}/connections", "post"),
        ("/projects/{project_id}/connections/{connection_id}", "delete"),
        ("/projects/{project_id}/static-routes", "post"),
        ("/projects/{project_id}/static-routes/{route_id}", "patch"),
        ("/projects/{project_id}/static-routes/{route_id}", "delete"),
    ]
    for path, method in protected:
        operation = paths[f"/api/v1{path}"][method]
        headers = [
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter["in"] == "header"
        ]
        assert "If-Match" in headers, (path, method)


def test_unprotected_operations_do_not_declare_if_match():
    paths = app.openapi()["paths"]
    for path, method in (("/projects", "post"), ("/projects/{project_id}", "get")):
        operation = paths[f"/api/v1{path}"][method]
        headers = [
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter["in"] == "header"
        ]
        assert "If-Match" not in headers
