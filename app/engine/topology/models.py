"""Immutable, pure-Python domain input types for the SYNTRA topology model.

These types are the engine's view of a vetted TASK-04 topology document. They
contain persisted configuration only; operational state, L2 domains and derived
warnings are computed by the functions in this module and are never stored here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.engine.ipv4.address import parse_ipv4

_UUID7_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_INTERFACE_NAME_RE = re.compile(r"^(FastEthernet0(/[0-6])?|GigabitEthernet0(/[0-2])?)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\S.*$")

# Unicode White_Space (TASK-04 section 5.2). Python's str.strip() is broader.
_WHITE_SPACE = {
    0x09,
    0x0A,
    0x0B,
    0x0C,
    0x0D,
    0x20,
    0x85,
    0xA0,
    0x1680,
    0x2028,
    0x2029,
    0x202F,
    0x205F,
    0x3000,
} | set(range(0x2000, 0x200B))

_INTERFACE_SPEED_MBPS = {
    "FAST_ETHERNET": 100,
    "GIGABIT_ETHERNET": 1000,
}


class DeviceKind(StrEnum):
    PC = "PC"
    SERVER = "SERVER"
    L2_SWITCH = "L2_SWITCH"
    ROUTER = "ROUTER"


class InterfaceKind(StrEnum):
    FAST_ETHERNET = "FAST_ETHERNET"
    GIGABIT_ETHERNET = "GIGABIT_ETHERNET"


class AdminState(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class CableType(StrEnum):
    GENERIC_ETHERNET = "GENERIC_ETHERNET"
    STRAIGHT_THROUGH = "STRAIGHT_THROUGH"
    CROSSOVER = "CROSSOVER"


class ChangeClass(StrEnum):
    TOPOLOGY = "TOPOLOGY"
    CONFIGURATION = "CONFIGURATION"
    PRESENTATION = "PRESENTATION"
    METADATA = "METADATA"
    MIXED = "MIXED"


class ChangeKind(StrEnum):
    PROJECT_CREATED = "PROJECT_CREATED"
    DEVICE_ADDED = "DEVICE_ADDED"
    DEVICE_REMOVED = "DEVICE_REMOVED"
    DEVICE_RENAMED = "DEVICE_RENAMED"
    DEVICE_MOVED = "DEVICE_MOVED"
    INTERFACE_ADMIN_STATE_CHANGED = "INTERFACE_ADMIN_STATE_CHANGED"
    INTERFACE_IPV4_CONFIGURED = "INTERFACE_IPV4_CONFIGURED"
    INTERFACE_IPV4_CLEARED = "INTERFACE_IPV4_CLEARED"
    HOST_GATEWAY_CONFIGURED = "HOST_GATEWAY_CONFIGURED"
    HOST_GATEWAY_CLEARED = "HOST_GATEWAY_CLEARED"
    CONNECTION_ADDED = "CONNECTION_ADDED"
    CONNECTION_REMOVED = "CONNECTION_REMOVED"
    STATIC_ROUTE_ADDED = "STATIC_ROUTE_ADDED"
    STATIC_ROUTE_EDITED = "STATIC_ROUTE_EDITED"
    STATIC_ROUTE_DELETED = "STATIC_ROUTE_DELETED"


class InterfaceOperationalState(StrEnum):
    ADMIN_DISABLED = "ADMIN_DISABLED"
    NO_LINK = "NO_LINK"
    PEER_DISABLED = "PEER_DISABLED"
    OPERATIONAL = "OPERATIONAL"


@dataclass(frozen=True, slots=True)
class Position:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        for coordinate_name in ("x", "y", "z"):
            value = getattr(self, coordinate_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{coordinate_name} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"{coordinate_name} must be finite")


@dataclass(frozen=True, slots=True)
class Ipv4Configuration:
    address: str
    prefix_length: int

    def __post_init__(self) -> None:
        if not isinstance(self.address, str):
            raise TypeError("address must be a str")
        parse_ipv4(self.address)
        if isinstance(self.prefix_length, bool) or not isinstance(self.prefix_length, int):
            raise TypeError("prefix_length must be an int")
        if not 1 <= self.prefix_length <= 30:
            raise ValueError("prefix_length must be between 1 and 30")


@dataclass(frozen=True, slots=True)
class InterfaceSlot:
    display_name: str
    ordinal: int
    interface_kind: InterfaceKind


@dataclass(frozen=True, slots=True)
class DerivedInterfaceState:
    interface_id: str
    operational_state: InterfaceOperationalState
    peer_interface_id: str | None
    effective_speed_mbps: int | None


@dataclass(frozen=True, slots=True)
class DerivedWarning:
    code: str
    interface_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str
    kind: DeviceKind
    display_name: str
    normalized_name: str
    device_sequence: int
    position: Position
    rotation_y_degrees: float = 0.0
    default_gateway_ipv4: str | None = None
    next_route_sequence: int | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _as_enum(DeviceKind, self.kind, "kind"))
        _require_uuid7("device_id", self.device_id)
        _require_nonempty_str("display_name", self.display_name)
        if len(self.display_name) > 64:
            raise ValueError("display_name must contain at most 64 characters")
        if not isinstance(self.normalized_name, str) or self.normalized_name != _normalize_name(
            self.display_name
        ):
            raise ValueError(
                "normalized_name must be the approved Unicode normalization of display_name"
            )
        if (
            isinstance(self.device_sequence, bool)
            or not isinstance(self.device_sequence, int)
            or self.device_sequence < 1
        ):
            raise ValueError("device_sequence must be a positive int")
        if not isinstance(self.position, Position):
            raise TypeError("position must be a Position")
        if isinstance(self.rotation_y_degrees, bool) or not isinstance(
            self.rotation_y_degrees, (int, float)
        ):
            raise TypeError("rotation_y_degrees must be a number")
        if not math.isfinite(self.rotation_y_degrees) or not -180 <= self.rotation_y_degrees < 180:
            raise ValueError("rotation_y_degrees must be in [-180, 180)")
        if self.default_gateway_ipv4 is not None:
            if self.kind not in {DeviceKind.PC, DeviceKind.SERVER}:
                raise ValueError("default_gateway_ipv4 is permitted only on PC and SERVER devices")
            parse_ipv4(self.default_gateway_ipv4)
        if self.kind == DeviceKind.ROUTER:
            if (
                self.next_route_sequence is None
                or isinstance(self.next_route_sequence, bool)
                or not isinstance(self.next_route_sequence, int)
                or self.next_route_sequence < 1
            ):
                raise ValueError("ROUTER devices require a positive next_route_sequence")
        elif self.next_route_sequence is not None:
            raise ValueError("next_route_sequence is permitted only on ROUTER devices")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a str")


@dataclass(frozen=True, slots=True)
class Interface:
    interface_id: str
    device_id: str
    display_name: str
    ordinal: int
    interface_kind: InterfaceKind
    admin_state: AdminState
    mac_address: str
    mac_sequence: int
    ipv4: Ipv4Configuration | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "interface_kind", _as_enum(InterfaceKind, self.interface_kind, "interface_kind")
        )
        object.__setattr__(
            self, "admin_state", _as_enum(AdminState, self.admin_state, "admin_state")
        )
        _require_uuid7("interface_id", self.interface_id)
        _require_uuid7("device_id", self.device_id)
        if not _INTERFACE_NAME_RE.fullmatch(self.display_name):
            raise ValueError("display_name is not a valid fixed inventory port name")
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or not 0 <= self.ordinal <= 7
        ):
            raise ValueError("ordinal must be an int between 0 and 7")
        parsed_mac = _parse_mac(self.mac_address)
        if _format_mac(parsed_mac) != self.mac_address:
            raise ValueError("mac_address must use canonical lowercase colon-separated form")
        if (
            isinstance(self.mac_sequence, bool)
            or not isinstance(self.mac_sequence, int)
            or self.mac_sequence < 1
            or self.mac_sequence > 0xFFFFFF
        ):
            raise ValueError("mac_sequence must be a positive 24-bit int")
        if self.ipv4 is not None and not isinstance(self.ipv4, Ipv4Configuration):
            raise TypeError("ipv4 must be an Ipv4Configuration or None")
        if self.interface_kind == InterfaceKind.FAST_ETHERNET and self.display_name.startswith(
            "GigabitEthernet"
        ):
            raise ValueError("interface_kind does not match display_name")
        if self.interface_kind == InterfaceKind.GIGABIT_ETHERNET and self.display_name.startswith(
            "FastEthernet"
        ):
            raise ValueError("interface_kind does not match display_name")


@dataclass(frozen=True, slots=True)
class Connection:
    connection_id: str
    interface_a_id: str
    interface_b_id: str
    cable_type: CableType
    connection_sequence: int
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "cable_type", _as_enum(CableType, self.cable_type, "cable_type"))
        _require_uuid7("connection_id", self.connection_id)
        _require_uuid7("interface_a_id", self.interface_a_id)
        _require_uuid7("interface_b_id", self.interface_b_id)
        if self.interface_a_id == self.interface_b_id:
            raise ValueError("a connection requires two distinct interfaces")
        if self.interface_a_id > self.interface_b_id:
            raise ValueError("interface_a_id must be lexicographically smaller than interface_b_id")
        if (
            isinstance(self.connection_sequence, bool)
            or not isinstance(self.connection_sequence, int)
            or self.connection_sequence < 1
        ):
            raise ValueError("connection_sequence must be a positive int")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a str")


@dataclass(frozen=True, slots=True)
class StaticRoute:
    route_id: str
    router_device_id: str
    destination_network: str
    prefix_length: int
    next_hop_ipv4: str
    route_sequence: int
    created_at: str = ""

    def __post_init__(self) -> None:
        _require_uuid7("route_id", self.route_id)
        _require_uuid7("router_device_id", self.router_device_id)
        if (
            isinstance(self.prefix_length, bool)
            or not isinstance(self.prefix_length, int)
            or not 0 <= self.prefix_length <= 32
        ):
            raise ValueError("prefix_length must be an int between 0 and 32")
        parse_ipv4(self.destination_network)
        parse_ipv4(self.next_hop_ipv4)
        if self.prefix_length == 0:
            if self.destination_network != "0.0.0.0":
                raise ValueError("only 0.0.0.0/0 is a valid default route")
        else:
            mask = (0xFFFFFFFF << (32 - self.prefix_length)) & 0xFFFFFFFF
            address = _ipv4_to_int(self.destination_network)
            if address & mask != address:
                raise ValueError("destination_network must be canonically aligned")
        if (
            isinstance(self.route_sequence, bool)
            or not isinstance(self.route_sequence, int)
            or self.route_sequence < 1
        ):
            raise ValueError("route_sequence must be a positive int")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a str")


@dataclass(frozen=True, slots=True)
class ProjectRevision:
    revision: int
    change_class: ChangeClass
    change_kinds: tuple[ChangeKind, ...]
    affected_entity_ids: tuple[str, ...] = ()
    committed_at: str = ""

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("revision must be a positive int")
        object.__setattr__(
            self, "change_class", _as_enum(ChangeClass, self.change_class, "change_class")
        )
        object.__setattr__(
            self,
            "change_kinds",
            tuple(_as_enum(ChangeKind, kind, "change_kinds") for kind in self.change_kinds),
        )
        if not self.change_kinds:
            raise ValueError("change_kinds must not be empty")
        if len(set(self.change_kinds)) != len(self.change_kinds):
            raise ValueError("change_kinds must be unique")
        for entity_id in self.affected_entity_ids:
            _require_uuid7("affected_entity_ids", entity_id)
        object.__setattr__(self, "affected_entity_ids", tuple(self.affected_entity_ids))
        if not isinstance(self.committed_at, str):
            raise TypeError("committed_at must be a str")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: str
    revision: int
    label: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        _require_uuid7("checkpoint_id", self.checkpoint_id)
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("revision must be a positive int")
        if self.label is not None:
            if not isinstance(self.label, str) or len(self.label) > 120:
                raise ValueError("label must be a str of at most 120 characters")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a str")


@dataclass(frozen=True, slots=True)
class SimulationSnapshotRef:
    snapshot_id: str
    project_id: str
    base_state_revision: int
    base_simulation_revision: int
    schema_version: str
    configuration_digest: str
    created_at: str = ""

    def __post_init__(self) -> None:
        _require_uuid7("snapshot_id", self.snapshot_id)
        _require_uuid7("project_id", self.project_id)
        for field_name in ("base_state_revision", "base_simulation_revision"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive int")
        if self.schema_version != "1.0.0":
            raise ValueError("schema_version must be 1.0.0")
        if not _SHA256_RE.fullmatch(self.configuration_digest):
            raise ValueError("configuration_digest must be a lowercase SHA-256 hex string")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a str")


@dataclass(frozen=True, slots=True)
class Project:
    project_id: str
    name: str
    description: str | None = None
    state_revision: int = 1
    simulation_revision: int = 1
    next_device_sequence: int = 1
    next_mac_sequence: int = 1
    next_connection_sequence: int = 1
    created_at: str = ""
    updated_at: str = ""
    devices: tuple[Device, ...] = field(default_factory=tuple)
    interfaces: tuple[Interface, ...] = field(default_factory=tuple)
    connections: tuple[Connection, ...] = field(default_factory=tuple)
    static_routes: tuple[StaticRoute, ...] = field(default_factory=tuple)
    revisions: tuple[ProjectRevision, ...] = field(default_factory=tuple)
    checkpoints: tuple[Checkpoint, ...] = field(default_factory=tuple)
    snapshot_refs: tuple[SimulationSnapshotRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "devices", tuple(self.devices))
        object.__setattr__(self, "interfaces", tuple(self.interfaces))
        object.__setattr__(self, "connections", tuple(self.connections))
        object.__setattr__(self, "static_routes", tuple(self.static_routes))
        object.__setattr__(self, "revisions", tuple(self.revisions))
        object.__setattr__(self, "checkpoints", tuple(self.checkpoints))
        object.__setattr__(self, "snapshot_refs", tuple(self.snapshot_refs))

        _require_uuid7("project_id", self.project_id)
        _require_nonempty_str("name", self.name)
        if len(self.name) > 64:
            raise ValueError("name must contain at most 64 characters")
        if self.description is not None and (
            not isinstance(self.description, str) or len(self.description) > 2000
        ):
            raise ValueError("description must be None or a str of at most 2000 characters")
        for field_name in ("state_revision", "simulation_revision"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive int")
        if self.simulation_revision > self.state_revision:
            raise ValueError("simulation_revision cannot exceed state_revision")
        for field_name in ("next_device_sequence", "next_mac_sequence", "next_connection_sequence"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive int")
        if not isinstance(self.created_at, str) or not isinstance(self.updated_at, str):
            raise TypeError("created_at and updated_at must be strs")
        _validate_project(self)


def _validate_project(project: Project) -> None:
    if len(project.devices) > 30:
        raise ValueError("a project may contain at most 30 devices")
    if len(project.connections) > 50:
        raise ValueError("a project may contain at most 50 connections")

    device_ids = {device.device_id for device in project.devices}
    if len(device_ids) != len(project.devices):
        raise ValueError("device_id values must be unique")
    normalized_names = [device.normalized_name for device in project.devices]
    if len(normalized_names) != len(set(normalized_names)):
        raise ValueError("normalized_name values must be unique within a project")

    device_sequences = [device.device_sequence for device in project.devices]
    if len(device_sequences) != len(set(device_sequences)):
        raise ValueError("device_sequence values must be unique within a project")
    if device_sequences and project.next_device_sequence <= max(device_sequences):
        raise ValueError("next_device_sequence must exceed every allocated device_sequence")

    interfaces_by_id = {interface.interface_id: interface for interface in project.interfaces}
    if len(interfaces_by_id) != len(project.interfaces):
        raise ValueError("interface_id values must be unique")

    interfaces_by_device: dict[str, list[Interface]] = {}
    for interface in project.interfaces:
        _require_uuid7("device_id", interface.device_id)
        if interface.device_id not in device_ids:
            raise ValueError("interface.device_id must reference a device in the same project")
        if interface.mac_address != mac_address_for(project.project_id, interface.mac_sequence):
            raise ValueError("mac_address does not match the approved MAC allocation projection")
        interfaces_by_device.setdefault(interface.device_id, []).append(interface)

    for device in project.devices:
        actual_inventory = tuple(
            (interface.display_name, interface.ordinal, interface.interface_kind)
            for interface in sorted(
                interfaces_by_device.get(device.device_id, ()),
                key=lambda item: (item.ordinal, item.interface_id),
            )
        )
        expected_inventory = tuple(
            (slot.display_name, slot.ordinal, slot.interface_kind)
            for slot in interface_inventory(device.kind)
        )
        if actual_inventory != expected_inventory:
            raise ValueError(
                f"device {device.device_id} does not have the exact approved port inventory"
            )
        if device.kind in {DeviceKind.PC, DeviceKind.SERVER}:
            if len(interfaces_by_device.get(device.device_id, ())) != 1:
                raise ValueError("PC and SERVER devices must have exactly one interface")
        if device.kind == DeviceKind.L2_SWITCH:
            if any(
                interface.ipv4 is not None
                for interface in interfaces_by_device.get(device.device_id, ())
            ):
                raise ValueError("L2_SWITCH interfaces must not carry IPv4 configuration")
        if device.kind == DeviceKind.ROUTER and device.next_route_sequence is None:
            raise ValueError("ROUTER devices require next_route_sequence")

    mac_sequences = [interface.mac_sequence for interface in project.interfaces]
    if len(mac_sequences) != len(set(mac_sequences)):
        raise ValueError("mac_sequence values must be unique within a project")
    if mac_sequences and project.next_mac_sequence <= max(mac_sequences):
        raise ValueError("next_mac_sequence must exceed every allocated mac_sequence")

    if len(project.connections) > 50:
        raise ValueError("a project may contain at most 50 connections")
    used_interfaces: set[str] = set()
    connection_sequences: list[int] = []
    for connection in project.connections:
        if (
            connection.interface_a_id not in interfaces_by_id
            or connection.interface_b_id not in interfaces_by_id
        ):
            raise ValueError("connection endpoints must reference interfaces in the same project")
        if (
            connection.interface_a_id in used_interfaces
            or connection.interface_b_id in used_interfaces
        ):
            raise ValueError("an interface may participate in at most one connection")
        used_interfaces.add(connection.interface_a_id)
        used_interfaces.add(connection.interface_b_id)
        connection_sequences.append(connection.connection_sequence)
    if len(connection_sequences) != len(set(connection_sequences)):
        raise ValueError("connection_sequence values must be unique within a project")
    if connection_sequences and project.next_connection_sequence <= max(connection_sequences):
        raise ValueError("next_connection_sequence must exceed every allocated connection_sequence")

    route_sequences_by_router: dict[str, list[int]] = {}
    for route in project.static_routes:
        _require_uuid7("router_device_id", route.router_device_id)
        if route.router_device_id not in device_ids:
            raise ValueError(
                "static route router_device_id must reference a device in the same project"
            )
        router = next(
            device for device in project.devices if device.device_id == route.router_device_id
        )
        if router.kind != DeviceKind.ROUTER:
            raise ValueError("static routes may only belong to ROUTER devices")
        route_sequences_by_router.setdefault(route.router_device_id, []).append(
            route.route_sequence
        )
    for router_id, sequences in route_sequences_by_router.items():
        router = next(device for device in project.devices if device.device_id == router_id)
        if router.next_route_sequence is None or router.next_route_sequence <= max(sequences):
            raise ValueError(
                "router next_route_sequence must exceed every allocated route_sequence"
            )
        if len(sequences) != len(set(sequences)):
            raise ValueError("route_sequence values must be unique within a router")

    if project.revisions:
        revisions = sorted(project.revisions, key=lambda item: item.revision)
        if [revision.revision for revision in revisions] != list(range(1, len(revisions) + 1)):
            raise ValueError("project revisions must be gapless starting at 1")
        if project.state_revision != len(revisions):
            raise ValueError("state_revision must equal the number of project revisions")
        simulation_relevant = [
            revision.revision
            for revision in revisions
            if revision.change_class
            in {ChangeClass.TOPOLOGY, ChangeClass.CONFIGURATION, ChangeClass.MIXED}
        ]
        expected_simulation_revision = max(simulation_relevant) if simulation_relevant else 1
        if project.simulation_revision != expected_simulation_revision:
            raise ValueError(
                "simulation_revision must identify the last simulation-relevant revision"
            )
        if project.updated_at != revisions[-1].committed_at:
            raise ValueError("updated_at must equal the last committed revision timestamp")
    for checkpoint in project.checkpoints:
        if checkpoint.revision > project.state_revision:
            raise ValueError("checkpoint revision must not exceed state_revision")
    for snapshot in project.snapshot_refs:
        if snapshot.project_id != project.project_id:
            raise ValueError("snapshot_ref project_id must match the project")
        if snapshot.schema_version != "1.0.0":
            raise ValueError("snapshot_ref schema_version must be 1.0.0")
        if snapshot.base_state_revision > project.state_revision:
            raise ValueError("snapshot base_state_revision must not exceed state_revision")
        if snapshot.base_simulation_revision > project.simulation_revision:
            raise ValueError(
                "snapshot base_simulation_revision must not exceed simulation_revision"
            )


_INTERFACE_INVENTORY: dict[DeviceKind, tuple[InterfaceSlot, ...]] = {
    DeviceKind.PC: (InterfaceSlot("FastEthernet0", 0, InterfaceKind.FAST_ETHERNET),),
    DeviceKind.SERVER: (InterfaceSlot("FastEthernet0", 0, InterfaceKind.FAST_ETHERNET),),
    DeviceKind.L2_SWITCH: (
        InterfaceSlot("FastEthernet0/1", 0, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("FastEthernet0/2", 1, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("FastEthernet0/3", 2, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("FastEthernet0/4", 3, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("FastEthernet0/5", 4, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("FastEthernet0/6", 5, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("GigabitEthernet0/1", 6, InterfaceKind.GIGABIT_ETHERNET),
        InterfaceSlot("GigabitEthernet0/2", 7, InterfaceKind.GIGABIT_ETHERNET),
    ),
    DeviceKind.ROUTER: (
        InterfaceSlot("FastEthernet0/0", 0, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("FastEthernet0/1", 1, InterfaceKind.FAST_ETHERNET),
        InterfaceSlot("GigabitEthernet0/0", 2, InterfaceKind.GIGABIT_ETHERNET),
        InterfaceSlot("GigabitEthernet0/1", 3, InterfaceKind.GIGABIT_ETHERNET),
    ),
}

PORT_INVENTORY: dict[DeviceKind, tuple[str, ...]] = {
    kind: tuple(slot.display_name for slot in slots) for kind, slots in _INTERFACE_INVENTORY.items()
}


def interface_inventory(kind: DeviceKind | str) -> tuple[InterfaceSlot, ...]:
    device_kind = _as_enum(DeviceKind, kind, "kind")
    return _INTERFACE_INVENTORY[device_kind]


def mac_address_for(project_id: str, mac_sequence: int) -> str:
    _require_uuid7("project_id", project_id)
    if isinstance(mac_sequence, bool) or not isinstance(mac_sequence, int) or mac_sequence < 1:
        raise ValueError("mac_sequence must be a positive int")
    if mac_sequence > 0xFFFFFF:
        raise ValueError("mac_sequence must fit in 24 bits")
    salt = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:4]
    raw = f"02{salt}{mac_sequence:06x}"
    return ":".join(raw[index : index + 2] for index in range(0, 12, 2))


mac_for = mac_address_for


def provision_interfaces(
    project_id: str,
    device_id: str,
    kind: DeviceKind | str,
    mac_sequences: Sequence[int],
    interface_ids: Sequence[str],
) -> tuple[Interface, ...]:
    _require_uuid7("project_id", project_id)
    _require_uuid7("device_id", device_id)
    device_kind = _as_enum(DeviceKind, kind, "kind")
    slots = interface_inventory(device_kind)
    sequences = tuple(mac_sequences)
    ids = tuple(interface_ids)
    if len(sequences) != len(slots) or len(ids) != len(slots):
        raise ValueError(
            "mac_sequences and interface_ids must contain one value for every inventory slot"
        )
    return tuple(
        Interface(
            interface_id=interface_id,
            device_id=device_id,
            display_name=slot.display_name,
            ordinal=slot.ordinal,
            interface_kind=slot.interface_kind,
            admin_state=AdminState.ENABLED,
            mac_address=mac_address_for(project_id, sequence),
            mac_sequence=sequence,
            ipv4=None,
        )
        for slot, sequence, interface_id in zip(slots, sequences, ids, strict=True)
    )


def interface_operational_state(
    project: Project,
    interface_id: str,
) -> DerivedInterfaceState:
    interface = _interface_by_id(project, interface_id)
    if interface.admin_state == AdminState.DISABLED:
        return DerivedInterfaceState(
            interface_id, InterfaceOperationalState.ADMIN_DISABLED, None, None
        )

    connection = _connection_for_interface(project, interface_id)
    if connection is None:
        return DerivedInterfaceState(interface_id, InterfaceOperationalState.NO_LINK, None, None)

    peer_id = (
        connection.interface_b_id
        if connection.interface_a_id == interface_id
        else connection.interface_a_id
    )
    peer = _interface_by_id(project, peer_id)
    if peer.admin_state == AdminState.DISABLED:
        return DerivedInterfaceState(
            interface_id, InterfaceOperationalState.PEER_DISABLED, peer_id, None
        )

    speed = min(
        _INTERFACE_SPEED_MBPS[interface.interface_kind.value],
        _INTERFACE_SPEED_MBPS[peer.interface_kind.value],
    )
    return DerivedInterfaceState(
        interface_id, InterfaceOperationalState.OPERATIONAL, peer_id, speed
    )


def derive_interface_states(project: Project) -> tuple[DerivedInterfaceState, ...]:
    _validate_project(project)
    return tuple(
        interface_operational_state(project, interface.interface_id)
        for interface in canonical_project(project).interfaces
    )


def l2_domains(project: Project) -> tuple[tuple[str, ...], ...]:
    _validate_project(project)
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_left] = root_right

    interfaces = {interface.interface_id: interface for interface in project.interfaces}
    devices = {device.device_id: device for device in project.devices}
    for interface_id in interfaces:
        find(interface_id)

    switch_ports: dict[str, list[str]] = {}
    for interface in project.interfaces:
        if devices[interface.device_id].kind == DeviceKind.L2_SWITCH:
            switch_ports.setdefault(interface.device_id, []).append(interface.interface_id)
    for ports in switch_ports.values():
        for port in ports[1:]:
            union(ports[0], port)

    for connection in project.connections:
        union(connection.interface_a_id, connection.interface_b_id)

    domains: dict[str, list[str]] = {}
    for interface_id in interfaces:
        domains.setdefault(find(interface_id), []).append(interface_id)
    return tuple(tuple(sorted(members)) for members in sorted(domains.values()))


def derive_warnings(project: Project) -> tuple[DerivedWarning, ...]:
    _validate_project(project)
    warnings: list[DerivedWarning] = []
    for domain in l2_domains(project):
        by_address: dict[str, list[str]] = {}
        for interface_id in domain:
            interface = _interface_by_id(project, interface_id)
            if interface.ipv4 is not None:
                by_address.setdefault(interface.ipv4.address, []).append(interface_id)
        for address, interface_ids in by_address.items():
            if len(interface_ids) > 1:
                warnings.append(
                    DerivedWarning(
                        code="DUPLICATE_IPV4_L2_DOMAIN",
                        interface_ids=tuple(sorted(interface_ids)),
                        message=f"Duplicate IPv4 address {address} in one L2 domain",
                    )
                )
    warnings.sort(key=lambda warning: warning.interface_ids)
    return tuple(warnings)


def canonical_project(project: Project) -> Project:
    _validate_project(project)
    devices = tuple(
        sorted(project.devices, key=lambda device: (device.device_sequence, device.device_id))
    )
    device_sequence_by_id = {device.device_id: device.device_sequence for device in devices}
    interfaces = tuple(
        sorted(
            project.interfaces,
            key=lambda interface: (
                device_sequence_by_id.get(interface.device_id, 0),
                interface.ordinal,
                interface.interface_id,
            ),
        )
    )
    connections = tuple(
        sorted(
            project.connections,
            key=lambda connection: (
                connection.connection_sequence,
                connection.interface_a_id,
                connection.interface_b_id,
            ),
        )
    )
    routes = tuple(
        sorted(
            project.static_routes,
            key=lambda route: (
                device_sequence_by_id.get(route.router_device_id, 0),
                route.route_sequence,
                route.route_id,
            ),
        )
    )
    revisions = tuple(sorted(project.revisions, key=lambda revision: revision.revision))
    checkpoints = tuple(
        sorted(
            project.checkpoints,
            key=lambda checkpoint: (checkpoint.revision, checkpoint.checkpoint_id),
        )
    )
    snapshot_refs = tuple(
        sorted(
            project.snapshot_refs, key=lambda snapshot: (snapshot.created_at, snapshot.snapshot_id)
        )
    )

    return Project(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        state_revision=project.state_revision,
        simulation_revision=project.simulation_revision,
        next_device_sequence=project.next_device_sequence,
        next_mac_sequence=project.next_mac_sequence,
        next_connection_sequence=project.next_connection_sequence,
        created_at=project.created_at,
        updated_at=project.updated_at,
        devices=devices,
        interfaces=interfaces,
        connections=connections,
        static_routes=routes,
        revisions=revisions,
        checkpoints=checkpoints,
        snapshot_refs=snapshot_refs,
    )


def project_from_fixture(document: Mapping[str, Any]) -> Project:
    if not isinstance(document, Mapping):
        raise TypeError("document must be a mapping")
    if document.get("schema_version") != "1.0.0":
        raise ValueError("document schema_version must be 1.0.0")

    project_raw = document["project"]
    devices = tuple(
        Device(
            device_id=raw["device_id"],
            kind=raw["kind"],
            display_name=raw["display_name"],
            normalized_name=raw["normalized_name"],
            device_sequence=raw["device_sequence"],
            position=Position(raw["position"]["x"], raw["position"]["y"], raw["position"]["z"]),
            rotation_y_degrees=raw.get("rotation_y_degrees", 0.0),
            default_gateway_ipv4=raw.get("default_gateway_ipv4"),
            next_route_sequence=raw.get("next_route_sequence"),
            created_at=raw["created_at"],
        )
        for raw in document["devices"]
    )

    interfaces = tuple(
        Interface(
            interface_id=raw["interface_id"],
            device_id=raw["device_id"],
            display_name=raw["display_name"],
            ordinal=raw["ordinal"],
            interface_kind=raw["interface_kind"],
            admin_state=raw["admin_state"],
            mac_address=raw["mac_address"],
            mac_sequence=raw["mac_sequence"],
            ipv4=None
            if raw.get("ipv4") is None
            else Ipv4Configuration(raw["ipv4"]["address"], raw["ipv4"]["prefix_length"]),
        )
        for raw in document["interfaces"]
    )

    connections = tuple(
        Connection(
            connection_id=raw["connection_id"],
            interface_a_id=raw["interface_a_id"],
            interface_b_id=raw["interface_b_id"],
            cable_type=raw["cable_type"],
            connection_sequence=raw["connection_sequence"],
            created_at=raw["created_at"],
        )
        for raw in document["connections"]
    )

    static_routes = tuple(
        StaticRoute(
            route_id=raw["route_id"],
            router_device_id=raw["router_device_id"],
            destination_network=raw["destination_network"],
            prefix_length=raw["prefix_length"],
            next_hop_ipv4=raw["next_hop_ipv4"],
            route_sequence=raw["route_sequence"],
            created_at=raw["created_at"],
        )
        for raw in document["static_routes"]
    )

    revisions = tuple(
        ProjectRevision(
            revision=raw["revision"],
            change_class=raw["change_class"],
            change_kinds=tuple(raw["change_kinds"]),
            affected_entity_ids=tuple(raw.get("affected_entity_ids", [])),
            committed_at=raw["committed_at"],
        )
        for raw in document.get("revisions", [])
    )

    project = Project(
        project_id=project_raw["project_id"],
        name=project_raw["name"],
        description=project_raw.get("description"),
        state_revision=project_raw["state_revision"],
        simulation_revision=project_raw["simulation_revision"],
        next_device_sequence=project_raw["next_device_sequence"],
        next_mac_sequence=project_raw["next_mac_sequence"],
        next_connection_sequence=project_raw["next_connection_sequence"],
        created_at=project_raw["created_at"],
        updated_at=project_raw["updated_at"],
        devices=devices,
        interfaces=interfaces,
        connections=connections,
        static_routes=static_routes,
        revisions=revisions,
        checkpoints=tuple(),
        snapshot_refs=tuple(),
    )

    for interface in project.interfaces:
        expected_mac = mac_address_for(project.project_id, interface.mac_sequence)
        if interface.mac_address != expected_mac:
            raise ValueError(f"interface {interface.interface_id} has an invalid MAC allocation")
    return canonical_project(project)


def load_project_from_fixture(path: str | Path) -> Project:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return project_from_fixture(document)


def _interface_by_id(project: Project, interface_id: str) -> Interface:
    for interface in project.interfaces:
        if interface.interface_id == interface_id:
            return interface
    raise ValueError(f"unknown interface_id: {interface_id}")


def _connection_for_interface(project: Project, interface_id: str) -> Connection | None:
    for connection in project.connections:
        if interface_id in (connection.interface_a_id, connection.interface_b_id):
            return connection
    return None


def _ipv4_to_int(value: str) -> int:
    parts = value.split(".")
    if len(parts) != 4:
        raise ValueError("invalid IPv4 address")
    result = 0
    for part in parts:
        if not part.isdigit():
            raise ValueError("invalid IPv4 address")
        octet = int(part)
        if octet > 255:
            raise ValueError("invalid IPv4 address")
        result = (result << 8) | octet
    return result


def _normalize_name(value: str) -> str:
    start, end = 0, len(value)
    while start < end and ord(value[start]) in _WHITE_SPACE:
        start += 1
    while end > start and ord(value[end - 1]) in _WHITE_SPACE:
        end -= 1
    return unicodedata.normalize("NFC", value[start:end]).casefold()


def _as_enum(enum_type: type, value: Any, field_name: str):
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as error:
            raise ValueError(f"{field_name} must be a valid {enum_type.__name__}") from error
    raise TypeError(f"{field_name} must be a {enum_type.__name__} or str")


def _require_uuid7(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or _UUID7_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase UUIDv7")


def _require_nonempty_str(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty str")


def _parse_mac(value: str) -> int:
    from app.engine.ethernet.mac import parse_mac

    return parse_mac(value)


def _format_mac(value: int) -> str:
    from app.engine.ethernet.mac import format_mac

    return format_mac(value)


__all__ = [
    "AdminState",
    "CableType",
    "ChangeClass",
    "ChangeKind",
    "Checkpoint",
    "Connection",
    "DerivedInterfaceState",
    "DerivedWarning",
    "Device",
    "DeviceKind",
    "Interface",
    "InterfaceKind",
    "InterfaceOperationalState",
    "InterfaceSlot",
    "Ipv4Configuration",
    "PORT_INVENTORY",
    "Position",
    "Project",
    "ProjectRevision",
    "SimulationSnapshotRef",
    "StaticRoute",
    "canonical_project",
    "derive_interface_states",
    "derive_warnings",
    "interface_inventory",
    "interface_operational_state",
    "is_uuid7",
    "l2_domains",
    "load_project_from_fixture",
    "mac_address_for",
    "mac_for",
    "normalize_name",
    "canonicalize_project",
    "operational_state",
    "project_from_fixture",
    "provision_interfaces",
    "validate_project",
]


def is_uuid7(value: Any) -> bool:
    return isinstance(value, str) and _UUID7_RE.fullmatch(value) is not None


# Compatibility aliases for the vocabulary used by the task and handoff documents.
normalize_name = _normalize_name
canonicalize_project = canonical_project
operational_state = interface_operational_state
validate_project = _validate_project
