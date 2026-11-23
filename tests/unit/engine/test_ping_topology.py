"""Phase 1: replay-input validation and snapshot projection → engine topology."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from app.db.base import uuid7
from app.db.document import configuration_projection
from app.engine.ping import (
    InvalidReplayInputError,
    parse_replay_input,
    topology_from_replay_input,
)
from app.engine.topology.models import (
    derive_interface_states,
    l2_domains,
    project_from_fixture,
)

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "reference" / "task04" / "fixtures"
FIXTURE_NAMES = ["rt-01", "rt-02", "rt-03", "rt-04", "rt-05"]
SNAPSHOT_ID = "019a5000-0000-7000-8000-000000000004"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _replay(document: dict) -> dict:
    """Reproduce the dict returned by ``replay_input(captured_snapshot)``."""
    return {
        "snapshot_id": SNAPSHOT_ID,
        "base_state_revision": document["project"]["state_revision"],
        "base_simulation_revision": document["project"]["simulation_revision"],
        "schema_version": "1.0.0",
        "configuration_digest": "a" * 64,
        "configuration": configuration_projection(document),
    }


def _device_signature(project) -> tuple:
    return tuple(
        sorted(
            (
                device.device_id,
                device.kind.value,
                device.device_sequence,
                device.default_gateway_ipv4,
            )
            for device in project.devices
        )
    )


def _interface_signature(project) -> tuple:
    return tuple(
        sorted(
            (
                interface.interface_id,
                interface.device_id,
                interface.ordinal,
                interface.interface_kind.value,
                interface.admin_state.value,
                interface.mac_address,
                interface.mac_sequence,
                None
                if interface.ipv4 is None
                else (interface.ipv4.address, interface.ipv4.prefix_length),
            )
            for interface in project.interfaces
        )
    )


def _connection_signature(project) -> tuple:
    return tuple(
        sorted(
            (
                connection.connection_id,
                connection.interface_a_id,
                connection.interface_b_id,
                connection.cable_type.value,
                connection.connection_sequence,
            )
            for connection in project.connections
        )
    )


def _route_signature(project) -> tuple:
    return tuple(
        sorted(
            (
                route.route_id,
                route.router_device_id,
                route.destination_network,
                route.prefix_length,
                route.next_hop_ipv4,
                route.route_sequence,
            )
            for route in project.static_routes
        )
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_adapter_preserves_every_simulation_relevant_value(fixture_name):
    document = _load_fixture(fixture_name)
    source = project_from_fixture(document)
    replay = _replay(document)

    snapshot = parse_replay_input(replay)
    assert snapshot.snapshot_id == SNAPSHOT_ID
    assert snapshot.project_id == document["project"]["project_id"]
    assert snapshot.base_state_revision == document["project"]["state_revision"]
    assert snapshot.base_simulation_revision == document["project"]["simulation_revision"]
    assert snapshot.configuration_digest == "a" * 64

    adapted = topology_from_replay_input(replay)
    assert adapted.project_id == source.project_id
    assert adapted.state_revision == source.state_revision
    assert adapted.simulation_revision == source.simulation_revision
    assert _device_signature(adapted) == _device_signature(source)
    assert _interface_signature(adapted) == _interface_signature(source)
    assert _connection_signature(adapted) == _connection_signature(source)
    assert _route_signature(adapted) == _route_signature(source)

    # Derived views depend only on the preserved simulation values.
    assert l2_domains(adapted) == l2_domains(source)
    assert derive_interface_states(adapted) == derive_interface_states(source)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_adapter_is_deterministic_and_synthesises_only_presentation_fields(fixture_name):
    replay = _replay(_load_fixture(fixture_name))
    first = topology_from_replay_input(replay)
    assert topology_from_replay_input(copy.deepcopy(replay)) == first

    for device in first.devices:
        assert device.display_name == f"{device.kind.value.lower()}-{device.device_sequence:02d}"
        assert device.normalized_name == device.display_name.casefold()
        assert (device.position.x, device.position.y, device.position.z) == (0.0, 0.0, 0.0)
        assert device.created_at == ""
    assert not first.revisions and not first.checkpoints and not first.snapshot_refs
    assert first.created_at == "" and first.updated_at == ""


def test_adapter_accepts_an_empty_projection():
    replay = {
        "snapshot_id": SNAPSHOT_ID,
        "base_state_revision": 1,
        "base_simulation_revision": 1,
        "schema_version": "1.0.0",
        "configuration_digest": "b" * 64,
        "configuration": {
            "schema_version": "1.0.0",
            "project": {"project_id": "019a5000-0000-7000-8000-000000000001"},
            "devices": [],
            "interfaces": [],
            "connections": [],
            "static_routes": [],
        },
    }
    project = topology_from_replay_input(replay)
    assert project.devices == () and project.interfaces == ()
    assert project.state_revision == 1 and project.simulation_revision == 1


# --- fail-closed validation ---------------------------------------------------


def _bad_replays():
    base = _replay(_load_fixture("rt-01"))

    def mutate(changes):
        value = copy.deepcopy(base)
        for key, new_value in changes.items():
            if new_value is _MISSING:
                value.pop(key, None)
            else:
                value[key] = new_value
        return value

    cases = [
        mutate({"configuration": _MISSING}),
        mutate({"schema_version": "2.0.0"}),
        mutate({"snapshot_id": str(uuid.uuid4())}),
        mutate({"configuration_digest": "not-a-digest"}),
        mutate({"base_state_revision": 0}),
        mutate({"base_simulation_revision": 0}),
        mutate({"base_simulation_revision": 99}),
    ]
    for key in ("devices", "interfaces", "connections", "static_routes"):
        value = copy.deepcopy(base)
        value["configuration"].pop(key)
        cases.append(value)
    return cases


_MISSING = object()


@pytest.mark.parametrize("replay", _bad_replays(), ids=range(11))
def test_malformed_replay_input_is_rejected(replay):
    with pytest.raises(InvalidReplayInputError):
        parse_replay_input(replay)


def test_unknown_interface_owner_is_rejected():
    replay = _replay(_load_fixture("rt-01"))
    replay["configuration"]["interfaces"][0]["device_id"] = str(uuid7())
    with pytest.raises(InvalidReplayInputError, match="must reference a device"):
        topology_from_replay_input(replay)


def test_invalid_inventory_slot_is_rejected():
    replay = _replay(_load_fixture("rt-01"))
    replay["configuration"]["interfaces"][0]["ordinal"] = 7
    with pytest.raises(InvalidReplayInputError, match="not an approved inventory slot"):
        topology_from_replay_input(replay)
