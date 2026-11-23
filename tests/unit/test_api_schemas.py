"""Strict TASK-07 schema tests (§14.2 step 2)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.api.v1.schemas import (
    AdminStateRequest,
    ApiEnvelope,
    ApiMeta,
    ConnectionCreateRequest,
    DeleteProjectRequest,
    DeviceCreateRequest,
    ErrorDetail,
    ErrorEnvelope,
    GatewayRequest,
    InterfaceIPv4Request,
    PingCreateRequest,
    ProjectCreateRequest,
    StaticRouteCreateRequest,
    StaticRoutePatchRequest,
)
from app.db.base import uuid7


def _connection(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "interface_a_id": str(uuid7()),
        "interface_b_id": str(uuid7()),
        "cable_type": "GENERIC_ETHERNET",
    }
    payload.update(overrides)
    return payload


def _ping(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "test_id": str(uuid7()),
        "source_device_id": str(uuid7()),
        "destination_device_id": str(uuid7()),
    }
    payload.update(overrides)
    return payload


# --- strictness -------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ProjectCreateRequest, {"name": "Lab", "surprise": 1}),
        (DeleteProjectRequest, {"confirm_name": "Lab", "surprise": 1}),
        (DeviceCreateRequest, {"kind": "PC", "display_name": "PC1", "surprise": 1}),
        (AdminStateRequest, {"admin_state": "ENABLED", "surprise": 1}),
        (ApiMeta, {"api_version": "v1", "surprise": 1}),
        (ErrorEnvelope, {"error": {"code": "X", "message": "m"}, "surprise": 1}),
    ],
)
def test_extra_fields_are_forbidden(model, payload):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(payload)


def test_envelope_forbids_extra_fields():
    envelope = ApiEnvelope[dict[str, Any]]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        envelope.model_validate({"data": {}, "meta": {}, "surprise": 1})


def test_nested_position_forbids_extra_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DeviceCreateRequest.model_validate(
            {"kind": "PC", "display_name": "PC1", "position": {"x": 0, "y": 0, "z": 0, "w": 1}}
        )


# --- UUIDv7 -----------------------------------------------------------------


@pytest.mark.parametrize("field", ["interface_a_id", "interface_b_id"])
def test_connection_ids_reject_non_uuid7(field):
    with pytest.raises(ValidationError, match="UUIDv7"):
        ConnectionCreateRequest.model_validate(_connection(**{field: str(uuid.uuid4())}))


@pytest.mark.parametrize("field", ["test_id", "source_device_id", "destination_device_id"])
def test_ping_ids_reject_non_uuid7(field):
    with pytest.raises(ValidationError, match="UUIDv7"):
        PingCreateRequest.model_validate(_ping(**{field: uuid.uuid4()}))


def test_route_router_id_rejects_non_uuid7():
    payload = {
        "router_device_id": str(uuid.uuid4()),
        "destination_network": "192.168.20.0",
        "prefix_length": 24,
        "next_hop_ipv4": "192.168.10.2",
    }
    with pytest.raises(ValidationError, match="UUIDv7"):
        StaticRouteCreateRequest.model_validate(payload)


def test_meta_command_id_rejects_non_uuid7():
    with pytest.raises(ValidationError, match="UUIDv7"):
        ApiMeta(command_id=uuid.uuid4())


def test_uuid7_ids_are_accepted_as_strings_and_uuid_instances():
    identifier = uuid7()
    parsed = PingCreateRequest.model_validate(
        _ping(test_id=identifier, source_device_id=str(uuid7()), destination_device_id=uuid7())
    )
    assert parsed.test_id == identifier
    assert parsed.test_id.version == 7


# --- strict IPv4 ------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "192.168.001.1",
        "١٩٢.١٦٨.١.١٠",  # non-ASCII decimal digits
        "192.168.1",
        "192.168.1.1.1",
        "256.1.1.1",
        "-1.1.1.1",
        " 192.168.1.1",
        "192.168.1.1 ",
        "",
    ],
)
def test_interface_ipv4_rejects_non_canonical_text(address):
    with pytest.raises(ValidationError):
        InterfaceIPv4Request.model_validate({"address": address, "prefix_length": 24})


def test_gateway_and_route_ipv4_use_the_same_strict_validator():
    for model, payload in (
        (GatewayRequest, {"gateway_ipv4": "192.168.001.1"}),
        (
            StaticRouteCreateRequest,
            {
                "router_device_id": uuid7(),
                "destination_network": "192.168.020.0",
                "prefix_length": 24,
                "next_hop_ipv4": "192.168.10.2",
            },
        ),
        (
            StaticRouteCreateRequest,
            {
                "router_device_id": uuid7(),
                "destination_network": "192.168.20.0",
                "prefix_length": 24,
                "next_hop_ipv4": "١٢٧.٠.٠.١",
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_canonical_ipv4_is_accepted():
    assert InterfaceIPv4Request(address="192.168.10.10", prefix_length=24).address == (
        "192.168.10.10"
    )


# --- ranges -----------------------------------------------------------------


@pytest.mark.parametrize("prefix", [0, 31, 32, -1])
def test_interface_prefix_only_allows_one_to_thirty(prefix):
    with pytest.raises(ValidationError):
        InterfaceIPv4Request.model_validate({"address": "192.168.1.10", "prefix_length": prefix})


@pytest.mark.parametrize("prefix", [1, 24, 30])
def test_interface_prefix_accepts_valid_range(prefix):
    assert InterfaceIPv4Request(address="192.168.1.10", prefix_length=prefix).prefix_length == (
        prefix
    )


@pytest.mark.parametrize("prefix", [-1, 33])
def test_route_prefix_rejects_out_of_range(prefix):
    payload = {
        "router_device_id": uuid7(),
        "destination_network": "192.168.20.0",
        "prefix_length": prefix,
        "next_hop_ipv4": "192.168.10.2",
    }
    with pytest.raises(ValidationError):
        StaticRouteCreateRequest.model_validate(payload)


@pytest.mark.parametrize("prefix", [0, 32])
def test_route_prefix_accepts_default_route_and_host_route(prefix):
    payload = {
        "router_device_id": uuid7(),
        "destination_network": "0.0.0.0" if prefix == 0 else "192.168.20.1",
        "prefix_length": prefix,
        "next_hop_ipv4": "192.168.10.2",
    }
    assert StaticRouteCreateRequest.model_validate(payload).prefix_length == prefix


@pytest.mark.parametrize("angle", [-180.0, 0.0, 179.9])
def test_rotation_accepts_half_open_range(angle):
    device = DeviceCreateRequest(kind="PC", display_name="PC1", rotation_y_degrees=angle)
    assert device.rotation_y_degrees == angle


@pytest.mark.parametrize("angle", [-180.1, 180.0])
def test_rotation_rejects_out_of_range(angle):
    with pytest.raises(ValidationError):
        DeviceCreateRequest.model_validate(
            {"kind": "PC", "display_name": "PC1", "rotation_y_degrees": angle}
        )


# --- ApiMeta invariant ------------------------------------------------------


def test_api_meta_without_ping_freshness_omits_is_current():
    meta = ApiMeta()
    assert meta.evidence_freshness is None
    assert meta.is_current is None
    assert meta.api_version == "v1"


@pytest.mark.parametrize(("freshness", "expected"), [("CURRENT", True), ("STALE", False)])
def test_api_meta_accepts_consistent_freshness(freshness, expected):
    meta = ApiMeta(evidence_freshness=freshness, is_current=expected)
    assert meta.is_current is expected


@pytest.mark.parametrize(("freshness", "wrong"), [("CURRENT", False), ("STALE", True)])
def test_api_meta_rejects_contradictory_freshness(freshness, wrong):
    with pytest.raises(ValidationError, match="is_current must match evidence_freshness"):
        ApiMeta(evidence_freshness=freshness, is_current=wrong)


def test_api_meta_rejects_is_current_without_freshness():
    with pytest.raises(ValidationError, match="is_current must match evidence_freshness"):
        ApiMeta(is_current=False)


def test_api_meta_rejects_unknown_api_version():
    with pytest.raises(ValidationError):
        ApiMeta(api_version="v2")


@pytest.mark.parametrize(
    ("base", "current", "freshness", "is_current"),
    [(10, 10, "CURRENT", True), (10, 11, "STALE", False)],
)
def test_for_ping_derives_freshness_from_revisions(base, current, freshness, is_current):
    meta = ApiMeta.for_ping(
        base_simulation_revision=base,
        current_simulation_revision=current,
        request_id="unity-request-000042",
        command_id=uuid7(),
    )
    assert meta.evidence_freshness == freshness
    assert meta.is_current is is_current
    assert meta.result_base_simulation_revision == base
    assert meta.current_simulation_revision == current
    assert meta.request_id == "unity-request-000042"


# --- envelopes --------------------------------------------------------------


def test_api_envelope_round_trip():
    envelope = ApiEnvelope[dict[str, Any]]
    payload = {"data": {"project_id": str(uuid7())}, "meta": ApiMeta().model_dump()}
    parsed = envelope.model_validate(payload)
    assert parsed.model_dump() == payload


def test_error_envelope_preserves_existing_shape():
    payload = {
        "error": {
            "code": "STALE_PROJECT_STATE",
            "message": "The project changed after the client loaded it.",
            "details": {
                "expected_state_revision": 12,
                "current_state_revision": 13,
                "current_simulation_revision": 13,
            },
            "request_id": "unity-request-000042",
        }
    }
    assert ErrorEnvelope.model_validate(payload).model_dump() == payload


def test_error_details_default_to_empty_mapping():
    envelope = ErrorEnvelope(error=ErrorDetail(code="X", message="failure"))
    assert envelope.model_dump() == {
        "error": {"code": "X", "message": "failure", "details": {}, "request_id": None}
    }


# --- static route patch -----------------------------------------------------


def test_route_patch_requires_at_least_one_field():
    with pytest.raises(ValidationError, match="at least one editable"):
        StaticRoutePatchRequest.model_validate({})


@pytest.mark.parametrize(
    "payload",
    [
        {"next_hop_ipv4": "192.168.10.2"},
        {"destination_network": "192.168.20.0", "prefix_length": 24},
        {"prefix_length": 0},
    ],
)
def test_route_patch_accepts_editable_fields(payload):
    assert StaticRoutePatchRequest.model_validate(payload).model_fields_set == set(payload)


def test_route_patch_forbids_backend_allocated_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StaticRoutePatchRequest.model_validate(
            {"route_id": str(uuid7()), "next_hop_ipv4": "192.168.10.2"}
        )
