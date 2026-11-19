"""Tests for the TASK-04 immutable engine domain model."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.engine.topology import models

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "reference" / "task04" / "fixtures"
PYTHON_UUID = "0190a4c2-0001-7000-8000-000000000004"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_project(device_count: int = 1, connection_count: int = 0) -> models.Project:
    devices = []
    interfaces = []
    interface_ids: list[str] = []
    next_interface_number = 1
    for device_number in range(1, device_count + 1):
        device_id = f"0190a4c2-0100-7000-8000-{device_number:012d}"
        devices.append(
            models.Device(
                device_id=device_id,
                kind=models.DeviceKind.PC,
                display_name=f"PC{device_number}",
                normalized_name=f"pc{device_number}",
                device_sequence=device_number,
                position=models.Position(float(device_number), 0.0, 0.0),
                created_at="2026-01-01T00:00:00Z",
            )
        )
        interface_id = f"0190a4c2-0200-7000-8000-{next_interface_number:012d}"
        next_interface_number += 1
        interface_ids.append(interface_id)
        interfaces.append(
            models.Interface(
                interface_id=interface_id,
                device_id=device_id,
                display_name="FastEthernet0",
                ordinal=0,
                interface_kind=models.InterfaceKind.FAST_ETHERNET,
                admin_state=models.AdminState.ENABLED,
                mac_address=models.mac_address_for(PYTHON_UUID, device_number),
                mac_sequence=device_number,
                ipv4=models.Ipv4Configuration(f"10.0.0.{device_number}", 24),
            )
        )

    connections = []
    for connection_number in range(1, connection_count + 1):
        left = interface_ids[2 * (connection_number - 1)]
        right = interface_ids[2 * (connection_number - 1) + 1]
        if left > right:
            left, right = right, left
        connections.append(
            models.Connection(
                connection_id=f"0190a4c2-0300-7000-8000-{connection_number:012d}",
                interface_a_id=left,
                interface_b_id=right,
                cable_type=models.CableType.GENERIC_ETHERNET,
                connection_sequence=connection_number,
                created_at="2026-01-01T00:00:00Z",
            )
        )

    return models.Project(
        project_id=PYTHON_UUID,
        name="Domain model test",
        state_revision=1,
        simulation_revision=1,
        next_device_sequence=device_count + 1,
        next_mac_sequence=device_count + 1,
        next_connection_sequence=connection_count + 1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        devices=tuple(devices),
        interfaces=tuple(interfaces),
        connections=tuple(connections),
        revisions=(),
    )


@pytest.mark.parametrize(
    "fixture_name", ["rt-01.json", "rt-02.json", "rt-03.json", "rt-04.json", "rt-05.json"]
)
def test_fixture_adapter_loads_all_reference_topologies(fixture_name: str) -> None:
    project = models.load_project_from_fixture(FIXTURES / fixture_name)

    assert models.is_uuid7(project.project_id)
    assert len(project.devices) <= 30
    assert len(project.connections) <= 50
    assert all(models.is_uuid7(device.device_id) for device in project.devices)
    assert all(models.is_uuid7(interface.interface_id) for interface in project.interfaces)


def test_uuid7_validation_rejects_invalid_values() -> None:
    assert models.is_uuid7("0190a4c2-0001-7000-8000-000000000004")
    assert not models.is_uuid7("not-a-uuid")
    assert not models.is_uuid7("0190A4C2-0001-7000-8000-000000000004")

    with pytest.raises(ValueError, match="UUIDv7"):
        models.Project(
            project_id="not-a-uuid",
            name="Invalid",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )


def test_port_inventory_is_exact_for_every_device_kind() -> None:
    assert models.PORT_INVENTORY[models.DeviceKind.PC] == ("FastEthernet0",)
    assert models.PORT_INVENTORY[models.DeviceKind.SERVER] == ("FastEthernet0",)
    assert models.PORT_INVENTORY[models.DeviceKind.L2_SWITCH] == (
        "FastEthernet0/1",
        "FastEthernet0/2",
        "FastEthernet0/3",
        "FastEthernet0/4",
        "FastEthernet0/5",
        "FastEthernet0/6",
        "GigabitEthernet0/1",
        "GigabitEthernet0/2",
    )
    assert models.PORT_INVENTORY[models.DeviceKind.ROUTER] == (
        "FastEthernet0/0",
        "FastEthernet0/1",
        "GigabitEthernet0/0",
        "GigabitEthernet0/1",
    )

    switch_inventory = models.interface_inventory(models.DeviceKind.L2_SWITCH)
    assert len(switch_inventory) == 8
    assert switch_inventory[0].ordinal == 0
    assert switch_inventory[-1].ordinal == 7


def test_mac_allocation_projection_matches_approved_fixture() -> None:
    project = models.load_project_from_fixture(FIXTURES / "rt-04.json")
    interface = next(item for item in project.interfaces if item.mac_sequence == 1)

    assert models.mac_address_for(project.project_id, 1) == "02:d3:10:00:00:01"
    assert interface.mac_address == "02:d3:10:00:00:01"
    assert models.mac_for(project.project_id, 2) == "02:d3:10:00:00:02"


def test_domain_models_are_immutable() -> None:
    project = models.load_project_from_fixture(FIXTURES / "rt-01.json")

    with pytest.raises(FrozenInstanceError):
        project.name = "changed"  # type: ignore[misc]


def test_canonical_sorting_is_deterministic() -> None:
    project = models.load_project_from_fixture(FIXTURES / "rt-04.json")
    canonical = models.canonical_project(project)

    assert [device.device_sequence for device in canonical.devices] == sorted(
        device.device_sequence for device in canonical.devices
    )
    device_sequence_by_id = {
        device.device_id: device.device_sequence for device in canonical.devices
    }
    interface_keys = [
        (device_sequence_by_id[interface.device_id], interface.ordinal, interface.interface_id)
        for interface in canonical.interfaces
    ]
    assert interface_keys == sorted(interface_keys)
    connection_keys = [
        (connection.connection_sequence, connection.interface_a_id, connection.interface_b_id)
        for connection in canonical.connections
    ]
    assert connection_keys == sorted(connection_keys)


def test_adapter_rejects_cross_project_interface_reference() -> None:
    document = _load_fixture("rt-01.json")
    document["interfaces"][0]["device_id"] = "0190a4c2-0100-7000-8000-000000000999"

    with pytest.raises(ValueError, match="device_id must reference"):
        models.project_from_fixture(document)


def test_adapter_rejects_cross_project_static_route_reference() -> None:
    document = _load_fixture("rt-04.json")
    document["static_routes"][0]["router_device_id"] = "0190a4c2-0100-7000-8000-000000000999"

    with pytest.raises(ValueError, match="router_device_id must reference"):
        models.project_from_fixture(document)


def test_adapter_preserves_route_sequence_gaps() -> None:
    document = _load_fixture("rt-04.json")
    document["static_routes"][0]["route_sequence"] = 5
    router_id = document["static_routes"][0]["router_device_id"]
    router = next(device for device in document["devices"] if device["device_id"] == router_id)
    router["next_route_sequence"] = 6

    project = models.project_from_fixture(document)

    assert project.static_routes[0].route_sequence == 5


def test_device_cap_is_enforced() -> None:
    with pytest.raises(ValueError, match="at most 30 devices"):
        _make_project(device_count=31)


def _make_connection_project(connection_count: int) -> models.Project:
    devices = []
    interfaces = []
    interface_ids: list[str] = []
    next_interface_number = 1
    for device_number in range(1, 14):
        device_id = f"0190a4c2-0100-7000-8000-{device_number:012d}"
        devices.append(
            models.Device(
                device_id=device_id,
                kind=models.DeviceKind.L2_SWITCH,
                display_name=f"SW{device_number}",
                normalized_name=f"sw{device_number}",
                device_sequence=device_number,
                position=models.Position(float(device_number), 0.0, 0.0),
                created_at="2026-01-01T00:00:00Z",
            )
        )
        for slot in models.interface_inventory(models.DeviceKind.L2_SWITCH):
            interface_id = f"0190a4c2-0200-7000-8000-{next_interface_number:012d}"
            next_interface_number += 1
            interface_ids.append(interface_id)
            interfaces.append(
                models.Interface(
                    interface_id=interface_id,
                    device_id=device_id,
                    display_name=slot.display_name,
                    ordinal=slot.ordinal,
                    interface_kind=slot.interface_kind,
                    admin_state=models.AdminState.ENABLED,
                    mac_address=models.mac_address_for(PYTHON_UUID, next_interface_number - 1),
                    mac_sequence=next_interface_number - 1,
                    ipv4=None,
                )
            )

    connections = []
    for connection_number in range(1, connection_count + 1):
        left = interface_ids[2 * (connection_number - 1)]
        right = interface_ids[2 * (connection_number - 1) + 1]
        if left > right:
            left, right = right, left
        connections.append(
            models.Connection(
                connection_id=f"0190a4c2-0300-7000-8000-{connection_number:012d}",
                interface_a_id=left,
                interface_b_id=right,
                cable_type=models.CableType.GENERIC_ETHERNET,
                connection_sequence=connection_number,
                created_at="2026-01-01T00:00:00Z",
            )
        )

    return models.Project(
        project_id=PYTHON_UUID,
        name="Connection cap test",
        state_revision=1,
        simulation_revision=1,
        next_device_sequence=14,
        next_mac_sequence=next_interface_number,
        next_connection_sequence=connection_count + 1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        devices=tuple(devices),
        interfaces=tuple(interfaces),
        connections=tuple(connections),
        revisions=(),
    )


def test_connection_cap_is_enforced() -> None:
    with pytest.raises(ValueError, match="at most 50 connections"):
        _make_connection_project(51)


def test_interface_operational_states_are_derived() -> None:
    project = models.load_project_from_fixture(FIXTURES / "rt-03.json")
    states = {state.interface_id: state for state in models.derive_interface_states(project)}

    connected = next(iter(project.connections))
    left = project.interfaces[0]
    assert (
        states[left.interface_id].operational_state == models.InterfaceOperationalState.OPERATIONAL
    )
    assert states[left.interface_id].effective_speed_mbps == 100
    assert states[left.interface_id].peer_interface_id == connected.interface_b_id

    disabled_project_document = _load_fixture("rt-03.json")
    disabled_interface = next(
        item
        for item in disabled_project_document["interfaces"]
        if item["interface_id"] == connected.interface_b_id
    )
    disabled_interface["admin_state"] = "DISABLED"
    disabled_project = models.project_from_fixture(disabled_project_document)
    disabled_states = models.derive_interface_states(disabled_project)
    assert disabled_states[0].operational_state == models.InterfaceOperationalState.PEER_DISABLED


def test_duplicate_ipv4_warning_is_derived_for_same_l2_domain() -> None:
    document = _load_fixture("rt-04.json")
    pc_interface = next(
        item for item in document["interfaces"] if item["interface_id"].endswith("000000000001")
    )
    router_interface = next(
        item for item in document["interfaces"] if item["interface_id"].endswith("000000000009")
    )
    pc_interface["ipv4"]["address"] = "192.168.10.99"
    router_interface["ipv4"]["address"] = "192.168.10.99"

    project = models.project_from_fixture(document)
    warnings = models.derive_warnings(project)

    assert len(warnings) == 1
    assert warnings[0].code == "DUPLICATE_IPV4_L2_DOMAIN"
    assert set(warnings[0].interface_ids) == {
        pc_interface["interface_id"],
        router_interface["interface_id"],
    }


def test_duplicate_ipv4_across_router_domains_does_not_warn() -> None:
    document = _load_fixture("rt-03.json")
    pc_interface = next(
        item for item in document["interfaces"] if item["interface_id"].endswith("000000000001")
    )
    remote_pc_interface = next(
        item for item in document["interfaces"] if item["interface_id"].endswith("000000000011")
    )
    pc_interface["ipv4"]["address"] = "10.0.0.7"
    remote_pc_interface["ipv4"]["address"] = "10.0.0.7"

    project = models.project_from_fixture(document)

    assert models.derive_warnings(project) == ()
