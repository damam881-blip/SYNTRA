"""Adapt verified replay input into the immutable engine topology (phase 1).

``replay_input(snapshot)`` returns the frozen TASK-04 §7.4 *behavioural
projection*, not the full canonical document accepted by
``project_from_fixture``: presentation names, positions, timestamps and the
revision array are deliberately absent. The simulation needs only identities,
kinds, admin states, addresses, links and routes, so this adapter synthesises
the mandatory domain fields deterministically from the projection.

Synthesised presentation values (device names, zero positions, empty
timestamps) are engine-internal only. They are never copied into Ping events,
diagnostics, hop evidence or any other TASK-05 result field.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.engine.topology.models import (
    Connection,
    Device,
    Interface,
    Ipv4Configuration,
    Position,
    Project,
    StaticRoute,
    canonical_project,
    interface_inventory,
    is_uuid7,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_SCHEMA_VERSION = "1.0.0"


class InvalidReplayInputError(ValueError):
    """Raised when replay input is not the verified snapshot projection expected."""


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    """Snapshot identity extracted from ``replay_input(snapshot)``."""

    snapshot_id: str
    project_id: str
    base_state_revision: int
    base_simulation_revision: int
    schema_version: str
    configuration_digest: str
    configuration: Mapping[str, object]


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvalidReplayInputError(f"{name} must be a mapping")
    return value


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvalidReplayInputError(f"{name} must be a sequence")
    return value


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidReplayInputError(f"{name} must be a non-empty str")
    return value


def _require_int(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidReplayInputError(f"{name} must be an int >= {minimum}")
    return value


def _require_uuid7(value: object, name: str) -> str:
    text = _require_str(value, name)
    if not is_uuid7(text):
        raise InvalidReplayInputError(f"{name} must be a lowercase UUIDv7")
    return text


def _require_row(value: object, name: str) -> Mapping[str, object]:
    return _require_mapping(value, name)


def parse_replay_input(replay_input: Mapping[str, object]) -> ReplaySnapshot:
    """Validate and extract the snapshot identity carried by replay input."""
    data = _require_mapping(replay_input, "replay_input")
    if data.get("schema_version") != _EXPECTED_SCHEMA_VERSION:
        raise InvalidReplayInputError("schema_version must be 1.0.0")

    snapshot_id = _require_uuid7(data.get("snapshot_id"), "snapshot_id")
    digest = _require_str(data.get("configuration_digest"), "configuration_digest")
    if not _SHA256_RE.fullmatch(digest):
        raise InvalidReplayInputError("configuration_digest must be lowercase SHA-256 hex")

    state_revision = _require_int(data.get("base_state_revision"), "base_state_revision", minimum=1)
    simulation_revision = _require_int(
        data.get("base_simulation_revision"), "base_simulation_revision", minimum=1
    )
    if simulation_revision > state_revision:
        raise InvalidReplayInputError("base_simulation_revision cannot exceed base_state_revision")

    configuration = _require_mapping(data.get("configuration"), "configuration")
    project_raw = _require_mapping(configuration.get("project"), "configuration.project")
    project_id = _require_uuid7(project_raw.get("project_id"), "configuration.project.project_id")

    for key in ("devices", "interfaces", "connections", "static_routes"):
        _require_sequence(configuration.get(key), f"configuration.{key}")

    return ReplaySnapshot(
        snapshot_id=snapshot_id,
        project_id=project_id,
        base_state_revision=state_revision,
        base_simulation_revision=simulation_revision,
        schema_version=_EXPECTED_SCHEMA_VERSION,
        configuration_digest=digest,
        configuration=configuration,
    )


def _max_sequence(rows: Sequence[object], key: str, *, default: int = 1) -> int:
    values = []
    for row in rows:
        value = _require_int(_require_row(row, key).get(key), key, minimum=1)
        values.append(value)
    return max(values) + 1 if values else default


def _build_devices(rows: Sequence[object], route_rows: Sequence[object]) -> tuple[Device, ...]:
    routes_by_router: dict[str, list[int]] = {}
    for row in route_rows:
        route = _require_row(row, "static_route")
        router_id = _require_uuid7(route.get("router_device_id"), "router_device_id")
        sequence = _require_int(route.get("route_sequence"), "route_sequence", minimum=1)
        routes_by_router.setdefault(router_id, []).append(sequence)

    devices: list[Device] = []
    for row in rows:
        raw = _require_row(row, "device")
        device_id = _require_uuid7(raw.get("device_id"), "device_id")
        kind = _require_str(raw.get("kind"), "kind")
        sequence = _require_int(raw.get("device_sequence"), "device_sequence", minimum=1)
        # Deterministic, ASCII-only presentation values: the projection has no
        # display names and no position. These never enter TASK-05 evidence.
        display_name = f"{kind.lower()}-{sequence:02d}"
        gateway = raw.get("default_gateway_ipv4")
        if gateway is not None and not isinstance(gateway, str):
            raise InvalidReplayInputError("default_gateway_ipv4 must be a str or None")
        next_route_sequence = None
        if kind == "ROUTER":
            owned = routes_by_router.get(device_id, [])
            next_route_sequence = max(owned) + 1 if owned else 1
        devices.append(
            Device(
                device_id=device_id,
                kind=kind,
                display_name=display_name,
                normalized_name=display_name.casefold(),
                device_sequence=sequence,
                position=Position(0.0, 0.0, 0.0),
                default_gateway_ipv4=gateway,
                next_route_sequence=next_route_sequence,
                created_at="",
            )
        )
    return tuple(devices)


def _build_interfaces(rows: Sequence[object], devices: Sequence[Device]) -> tuple[Interface, ...]:
    kind_by_device = {device.device_id: device.kind for device in devices}
    interfaces: list[Interface] = []
    for row in rows:
        raw = _require_row(row, "interface")
        device_id = _require_uuid7(raw.get("device_id"), "interface.device_id")
        if device_id not in kind_by_device:
            raise InvalidReplayInputError("interface.device_id must reference a device")
        interface_kind = _require_str(raw.get("interface_kind"), "interface_kind")
        ordinal = _require_int(raw.get("ordinal"), "ordinal", minimum=0)
        slots = [
            slot
            for slot in interface_inventory(kind_by_device[device_id])
            if slot.ordinal == ordinal
        ]
        if not slots or slots[0].interface_kind.value != interface_kind:
            raise InvalidReplayInputError(
                "interface_kind and ordinal are not an approved inventory slot"
            )
        ipv4_raw = raw.get("ipv4")
        ipv4 = None
        if ipv4_raw is not None:
            ipv4_data = _require_mapping(ipv4_raw, "interface.ipv4")
            address = _require_str(ipv4_data.get("address"), "interface.ipv4.address")
            prefix_length = _require_int(
                ipv4_data.get("prefix_length"), "interface.ipv4.prefix_length", minimum=1
            )
            ipv4 = Ipv4Configuration(address, prefix_length)
        interfaces.append(
            Interface(
                interface_id=_require_uuid7(raw.get("interface_id"), "interface_id"),
                device_id=device_id,
                display_name=slots[0].display_name,
                ordinal=ordinal,
                interface_kind=interface_kind,
                admin_state=_require_str(raw.get("admin_state"), "admin_state"),
                mac_address=_require_str(raw.get("mac_address"), "mac_address"),
                mac_sequence=_require_int(raw.get("mac_sequence"), "mac_sequence", minimum=1),
                ipv4=ipv4,
            )
        )
    return tuple(interfaces)


def _build_connections(rows: Sequence[object]) -> tuple[Connection, ...]:
    return tuple(
        Connection(
            connection_id=_require_uuid7(raw.get("connection_id"), "connection_id"),
            interface_a_id=_require_uuid7(raw.get("interface_a_id"), "interface_a_id"),
            interface_b_id=_require_uuid7(raw.get("interface_b_id"), "interface_b_id"),
            cable_type=_require_str(raw.get("cable_type"), "cable_type"),
            connection_sequence=_require_int(
                raw.get("connection_sequence"), "connection_sequence", minimum=1
            ),
            created_at="",
        )
        for row in rows
        for raw in [_require_row(row, "connection")]
    )


def _build_routes(rows: Sequence[object]) -> tuple[StaticRoute, ...]:
    return tuple(
        StaticRoute(
            route_id=_require_uuid7(raw.get("route_id"), "route_id"),
            router_device_id=_require_uuid7(raw.get("router_device_id"), "router_device_id"),
            destination_network=_require_str(raw.get("destination_network"), "destination_network"),
            prefix_length=_require_int(raw.get("prefix_length"), "prefix_length", minimum=0),
            next_hop_ipv4=_require_str(raw.get("next_hop_ipv4"), "next_hop_ipv4"),
            route_sequence=_require_int(raw.get("route_sequence"), "route_sequence", minimum=1),
            created_at="",
        )
        for row in rows
        for raw in [_require_row(row, "static_route")]
    )


def topology_from_replay_input(replay_input: Mapping[str, object]) -> Project:
    """Build a canonical engine ``Project`` from a verified replay snapshot.

    All simulation-relevant values come from the frozen projection. Missing
    presentation metadata is derived deterministically; no current database
    state is consulted, so the result is exactly the configuration that was
    snapshotted.
    """
    snapshot = parse_replay_input(replay_input)
    configuration = snapshot.configuration
    assert isinstance(configuration["devices"], Sequence)
    assert isinstance(configuration["interfaces"], Sequence)
    assert isinstance(configuration["connections"], Sequence)
    assert isinstance(configuration["static_routes"], Sequence)

    device_rows = configuration["devices"]
    route_rows = configuration["static_routes"]
    devices = _build_devices(device_rows, route_rows)
    interfaces = _build_interfaces(configuration["interfaces"], devices)
    connections = _build_connections(configuration["connections"])
    routes = _build_routes(route_rows)

    project = Project(
        project_id=snapshot.project_id,
        name=snapshot.project_id,
        state_revision=snapshot.base_state_revision,
        simulation_revision=snapshot.base_simulation_revision,
        next_device_sequence=_max_sequence(device_rows, "device_sequence"),
        next_mac_sequence=_max_sequence(configuration["interfaces"], "mac_sequence"),
        next_connection_sequence=_max_sequence(configuration["connections"], "connection_sequence"),
        created_at="",
        updated_at="",
        devices=devices,
        interfaces=interfaces,
        connections=connections,
        static_routes=routes,
    )
    return canonical_project(project)


__all__ = [
    "InvalidReplayInputError",
    "ReplaySnapshot",
    "parse_replay_input",
    "topology_from_replay_input",
]
