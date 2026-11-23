"""Project lifecycle service: CRUD, commits, checkpoints, deletion.

Every mutating function follows the same transaction policy:

1. ``SELECT ... FOR UPDATE`` locks the project row;
2. all entity changes happen on that locked aggregate;
3. ``project.state_revision`` is incremented and flushed *before* the
   append-only ``project_revision`` row (the gaplessness trigger requires this);
4. an action-log row references the new revision;
5. the caller's transaction commits once.

Consequently two concurrent mutations serialise, and any exception rolls the
whole unit back leaving the prior committed state intact.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import ipv4_to_int, utc_now, uuid7
from app.db.document import project_document, read_project
from app.db.enums import (
    AdminState,
    CableType,
    ChangeClass,
    ChangeKind,
    DeviceKind,
)
from app.db.errors import (
    ContractValidationError,
    DeletionConfirmationError,
    IntegrityConflictError,
    PreconditionConflictError,
    ProjectNotFoundError,
)
from app.db.models import (
    ActionLog,
    Checkpoint,
    Device,
    Interface,
    Project,
    ProjectRevision,
    ProjectTombstone,
    StaticRoute,
)
from app.db.models import (
    Connection as ConnectionModel,
)
from app.engine.topology.models import interface_inventory, mac_address_for
from app.modules.projects.validation import (
    cable_type_allowed,
    validate_host_address,
    validate_special_address,
)

# TASK-04 Unicode White_Space code points used by the approved normalisation rule.
_WHITE_SPACE = frozenset(
    [9, 10, 11, 12, 13, 32, 133, 160, 5760]
    + list(range(8192, 8203))
    + [8232, 8233, 8239, 8287, 12288]
)

SIMULATION_IMPACTING_CLASSES = frozenset(
    {ChangeClass.TOPOLOGY, ChangeClass.CONFIGURATION, ChangeClass.MIXED}
)

DEFAULT_ACTOR = "system"


@dataclass(frozen=True)
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


def normalize_name(value: str) -> str:
    """NFC(trim(display_name)) then Unicode full case folding (TASK-04 T-DISP)."""
    if not isinstance(value, str):
        raise TypeError("display name must be a string")
    start, end = 0, len(value)
    while start < end and ord(value[start]) in _WHITE_SPACE:
        start += 1
    while end > start and ord(value[end - 1]) in _WHITE_SPACE:
        end -= 1
    trimmed = value[start:end]
    return unicodedata.normalize("NFC", trimmed).casefold()


def _require_text(value: str, field: str, *, max_length: int) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise PreconditionConflictError(f"{field} must not be blank")
    if len(trimmed) > max_length:
        raise PreconditionConflictError(f"{field} must be at most {max_length} characters")
    return trimmed


def _as_uuid(value: uuid.UUID | str, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as error:
        raise PreconditionConflictError(f"{field} is not a valid UUID") from error


def _entity_type(kind: Any) -> str:
    return kind.value if hasattr(kind, "value") else str(kind)


def _lock(session: Session, project_id: uuid.UUID) -> Project:
    project = session.scalars(
        select(Project).where(Project.project_id == project_id).with_for_update(nowait=False)
    ).one_or_none()
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} does not exist")
    return project


def _get_device(session: Session, project_id: uuid.UUID, device_id: uuid.UUID) -> Device:
    device = session.scalars(
        select(Device).where(Device.project_id == project_id, Device.device_id == device_id)
    ).one_or_none()
    if device is None:
        raise PreconditionConflictError(f"device {device_id} is not in project {project_id}")
    return device


def _get_interface(session: Session, project_id: uuid.UUID, interface_id: uuid.UUID) -> Interface:
    interface = session.scalars(
        select(Interface).where(
            Interface.project_id == project_id, Interface.interface_id == interface_id
        )
    ).one_or_none()
    if interface is None:
        raise PreconditionConflictError(f"interface {interface_id} is not in project {project_id}")
    return interface


def _log_action(
    session: Session,
    project: Project,
    *,
    actor: str,
    action_kind: str,
    revision: int,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> ActionLog:
    log = ActionLog(
        log_id=uuid7(),
        project_id=project.project_id,
        actor=actor[:128],
        action_kind=action_kind[:64],
        entity_type=None if entity_type is None else entity_type[:32],
        entity_id=entity_id,
        revision=revision,
        detail_json=detail or {},
    )
    session.add(log)
    session.flush()
    return log


def _commit_mutation(
    session: Session,
    project: Project,
    *,
    actor: str,
    change_class: ChangeClass,
    change_kinds: list[ChangeKind | str],
    affected_entity_ids: list[uuid.UUID],
    action_kind: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> ProjectRevision:
    kinds: list[str] = []
    for kind in change_kinds:
        spelling = _entity_type(kind)
        if spelling not in kinds:
            kinds.append(spelling)
    if not kinds:
        raise ContractValidationError("a commit requires at least one change kind")

    project.state_revision += 1
    if change_class in SIMULATION_IMPACTING_CLASSES:
        project.simulation_revision = project.state_revision
    session.flush()

    revision = ProjectRevision(
        project_id=project.project_id,
        revision=project.state_revision,
        change_class=change_class,
        change_kinds=kinds,
        affected_entity_ids=list(dict.fromkeys(affected_entity_ids)),
        committed_at=utc_now(),
    )
    session.add(revision)
    session.flush()

    _log_action(
        session,
        project,
        actor=actor,
        action_kind=action_kind,
        revision=revision.revision,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
    )
    return revision


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


def create_project(
    session: Session,
    *,
    name: str,
    description: str | None = None,
    actor: str = DEFAULT_ACTOR,
) -> Project:
    clean_name = _require_text(name, "name", max_length=64)
    clean_description = (
        None if description is None else _require_text(description, "description", max_length=2000)
    )
    project = Project(
        project_id=uuid7(),
        name=clean_name,
        description=clean_description,
        state_revision=1,
        simulation_revision=1,
        next_device_sequence=1,
        next_mac_sequence=1,
        next_connection_sequence=1,
    )
    session.add(project)
    session.flush()

    revision = ProjectRevision(
        project_id=project.project_id,
        revision=1,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.PROJECT_CREATED.value],
        affected_entity_ids=[project.project_id],
        committed_at=utc_now(),
    )
    session.add(revision)
    session.flush()
    _log_action(
        session,
        project,
        actor=actor,
        action_kind="PROJECT_CREATED",
        revision=1,
        entity_type="project",
        entity_id=project.project_id,
        detail={"name": clean_name},
    )
    return project


def open_project(
    session: Session,
    project_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Return the canonical TASK-04 document at one consistent snapshot view."""
    identifier = _as_uuid(project_id, "project_id")
    return project_document(session, identifier)


def list_checkpoints(session: Session, project_id: uuid.UUID | str) -> list[Checkpoint]:
    identifier = _as_uuid(project_id, "project_id")
    read_project(session, identifier)
    return list(
        session.scalars(
            select(Checkpoint)
            .where(Checkpoint.project_id == identifier)
            .order_by(Checkpoint.created_at, Checkpoint.checkpoint_id)
        )
    )


def save_project(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    label: str | None = None,
    actor: str = DEFAULT_ACTOR,
) -> Checkpoint:
    """Record a checkpoint marker at the current revision; never bumps revisions."""
    identifier = _as_uuid(project_id, "project_id")
    project = _lock(session, identifier)
    clean_label: str | None = None
    if label is not None:
        clean_label = _require_text(label, "label", max_length=120)
    checkpoint = Checkpoint(
        checkpoint_id=uuid7(),
        project_id=identifier,
        revision=project.state_revision,
        label=clean_label,
        created_at=utc_now(),
    )
    session.add(checkpoint)
    session.flush()
    _log_action(
        session,
        project,
        actor=actor,
        action_kind="CHECKPOINT_SAVED",
        revision=project.state_revision,
        entity_type="checkpoint",
        entity_id=checkpoint.checkpoint_id,
        detail={"revision": project.state_revision, "label": clean_label},
    )
    return checkpoint


def rename_device(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    device_id: uuid.UUID | str,
    display_name: str,
    actor: str = DEFAULT_ACTOR,
) -> Device:
    """Rename a device; presentation/metadata class, no simulation impact."""
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(device_id, "device_id")
    project = _lock(session, identifier)
    device = _get_device(session, identifier, target_id)
    clean_name = _require_text(display_name, "display_name", max_length=64)
    normalized = normalize_name(clean_name)
    existing = session.scalars(
        select(Device.device_id).where(
            Device.project_id == identifier,
            Device.normalized_name == normalized,
            Device.device_id != target_id,
        )
    ).first()
    if existing is not None:
        raise IntegrityConflictError(f"device name {clean_name!r} already exists in project")
    if normalized == device.normalized_name and clean_name == device.display_name:
        raise PreconditionConflictError("device name was not changed")

    device.display_name = clean_name
    device.normalized_name = normalized
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.METADATA,
        change_kinds=[ChangeKind.DEVICE_RENAMED],
        affected_entity_ids=[target_id],
        action_kind="DEVICE_RENAMED",
        entity_type="device",
        entity_id=target_id,
        detail={"display_name": clean_name, "normalized_name": normalized},
    )
    return device


def delete_project(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    confirm_name: str,
    actor: str = DEFAULT_ACTOR,
) -> ProjectTombstone:
    """Purge a project after an exact-name confirmation.

    The tombstone is written first so deletion remains auditable, then
    ``syntra.purge_mode`` allows the cascade to remove immutable rows.
    """
    identifier = _as_uuid(project_id, "project_id")
    project = _lock(session, identifier)
    if confirm_name != project.name:
        raise DeletionConfirmationError(
            "deletion refused: confirmation name does not match the project name"
        )

    tombstone = ProjectTombstone(
        project_id=project.project_id,
        project_name=project.name,
        last_state_revision=project.state_revision,
        last_simulation_revision=project.simulation_revision,
        deleted_by=actor[:128],
        deleted_at=utc_now(),
    )
    session.add(tombstone)
    session.flush()

    session.execute(text("SET LOCAL syntra.purge_mode = 'on'"))
    session.delete(project)
    session.flush()
    return tombstone


# ---------------------------------------------------------------------------
# Topology mutations
# ---------------------------------------------------------------------------


def _require_kind(value: DeviceKind | str, enum_type: type, field: str):
    try:
        return enum_type(value)
    except ValueError as error:
        raise PreconditionConflictError(
            f"{field} must be one of {[member.value for member in enum_type]}"
        ) from error


def _validate_prefix(prefix: int, *, minimum: int, maximum: int, field: str) -> int:
    if isinstance(prefix, bool) or not isinstance(prefix, int):
        raise PreconditionConflictError(f"{field} must be an integer")
    if not minimum <= prefix <= maximum:
        raise PreconditionConflictError(f"{field} must be between {minimum} and {maximum}")
    return prefix


def _network_aligned(address: str, prefix: int) -> int:
    value = ipv4_to_int(address)
    host_bits = 32 - prefix
    if host_bits > 0 and (value & ((1 << host_bits) - 1)) != 0:
        raise PreconditionConflictError(f"{address}/{prefix} is not a canonical network address")
    return value


def add_device(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    kind: DeviceKind | str,
    display_name: str,
    position: Position | None = None,
    rotation_y_degrees: float = 0.0,
    actor: str = DEFAULT_ACTOR,
) -> Device:
    identifier = _as_uuid(project_id, "project_id")
    device_kind = _require_kind(kind, DeviceKind, "kind")
    clean_name = _require_text(display_name, "display_name", max_length=64)
    normalized = normalize_name(clean_name)
    if not -180.0 <= float(rotation_y_degrees) < 180.0:
        raise PreconditionConflictError("rotation_y_degrees must be in [-180, 180)")

    project = _lock(session, identifier)
    clash = session.scalars(
        select(Device.device_id).where(
            Device.project_id == identifier,
            Device.normalized_name == normalized,
        )
    ).first()
    if clash is not None:
        raise IntegrityConflictError(f"device name {clean_name!r} already exists in project")

    slot_inventory = interface_inventory(device_kind)
    place = position or Position()

    device = Device(
        device_id=uuid7(),
        project_id=identifier,
        kind=device_kind,
        display_name=clean_name,
        normalized_name=normalized,
        device_sequence=project.next_device_sequence,
        default_gateway_ipv4=None,
        position_x=float(place.x),
        position_y=float(place.y),
        position_z=float(place.z),
        rotation_y_degrees=float(rotation_y_degrees),
        next_route_sequence=1 if device_kind is DeviceKind.ROUTER else None,
        created_at=utc_now(),
    )
    session.add(device)
    project.next_device_sequence += 1

    allocated_interfaces: list[Interface] = []
    for slot in slot_inventory:
        mac_sequence = project.next_mac_sequence
        project.next_mac_sequence += 1
        interface = Interface(
            interface_id=uuid7(),
            project_id=identifier,
            device_id=device.device_id,
            display_name=slot.display_name,
            ordinal=slot.ordinal,
            interface_kind=slot.interface_kind,
            admin_state=AdminState.ENABLED,
            mac_address=mac_address_for(str(identifier), mac_sequence),
            mac_sequence=mac_sequence,
            ipv4_address=None,
            ipv4_prefix_length=None,
        )
        session.add(interface)
        allocated_interfaces.append(interface)
    session.flush()

    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.DEVICE_ADDED],
        affected_entity_ids=[device.device_id]
        + [interface.interface_id for interface in allocated_interfaces],
        action_kind="DEVICE_ADDED",
        entity_type="device",
        entity_id=device.device_id,
        detail={"kind": _entity_type(device_kind), "display_name": clean_name},
    )
    return device


def remove_device(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    device_id: uuid.UUID | str,
    actor: str = DEFAULT_ACTOR,
) -> None:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(device_id, "device_id")
    project = _lock(session, identifier)
    device = _get_device(session, identifier, target_id)

    interface_ids = [
        row[0]
        for row in session.execute(
            select(Interface.interface_id).where(
                Interface.project_id == identifier, Interface.device_id == target_id
            )
        ).all()
    ]
    removed_connections = list(
        session.scalars(
            select(ConnectionModel).where(
                ConnectionModel.project_id == identifier,
                (
                    ConnectionModel.interface_a_id.in_(interface_ids)
                    | ConnectionModel.interface_b_id.in_(interface_ids)
                ),
            )
        )
    )
    removed_routes = list(
        session.scalars(
            select(StaticRoute).where(
                StaticRoute.project_id == identifier,
                StaticRoute.router_device_id == target_id,
            )
        )
    )
    for connection in removed_connections:
        session.delete(connection)
    for route in removed_routes:
        session.delete(route)
    session.delete(device)
    session.flush()

    kinds = [ChangeKind.DEVICE_REMOVED]
    if removed_connections:
        kinds.append(ChangeKind.CONNECTION_REMOVED)
    if removed_routes:
        kinds.append(ChangeKind.STATIC_ROUTE_DELETED)
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=kinds,
        affected_entity_ids=[target_id, *interface_ids]
        + [connection.connection_id for connection in removed_connections]
        + [route.route_id for route in removed_routes],
        action_kind="DEVICE_REMOVED",
        entity_type="device",
        entity_id=target_id,
        detail={
            "connections_removed": len(removed_connections),
            "routes_removed": len(removed_routes),
        },
    )


def set_interface_admin_state(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    interface_id: uuid.UUID | str,
    admin_state: AdminState | str,
    actor: str = DEFAULT_ACTOR,
) -> Interface:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(interface_id, "interface_id")
    state = _require_kind(admin_state, AdminState, "admin_state")
    project = _lock(session, identifier)
    interface = _get_interface(session, identifier, target_id)
    if interface.admin_state is state:
        raise PreconditionConflictError("interface admin state was not changed")
    interface.admin_state = state
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.CONFIGURATION,
        change_kinds=[ChangeKind.INTERFACE_ADMIN_STATE_CHANGED],
        affected_entity_ids=[target_id],
        action_kind="INTERFACE_ADMIN_STATE_CHANGED",
        entity_type="interface",
        entity_id=target_id,
        detail={"admin_state": _entity_type(state)},
    )
    return interface


def configure_interface_ipv4(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    interface_id: uuid.UUID | str,
    address: str,
    prefix_length: int,
    actor: str = DEFAULT_ACTOR,
) -> Interface:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(interface_id, "interface_id")
    prefix = _validate_prefix(prefix_length, minimum=1, maximum=30, field="prefix_length")
    validate_host_address(address, prefix)
    value = ipv4_to_int(address)
    project = _lock(session, identifier)
    interface = _get_interface(session, identifier, target_id)
    if interface.ipv4_address == value and interface.ipv4_prefix_length == prefix:
        raise PreconditionConflictError("IPv4 configuration was not changed")
    interface.ipv4_address = value
    interface.ipv4_prefix_length = prefix
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.CONFIGURATION,
        change_kinds=[ChangeKind.INTERFACE_IPV4_CONFIGURED],
        affected_entity_ids=[target_id],
        action_kind="INTERFACE_IPV4_CONFIGURED",
        entity_type="interface",
        entity_id=target_id,
        detail={"address": address, "prefix_length": prefix},
    )
    return interface


def clear_interface_ipv4(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    interface_id: uuid.UUID | str,
    actor: str = DEFAULT_ACTOR,
) -> Interface:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(interface_id, "interface_id")
    project = _lock(session, identifier)
    interface = _get_interface(session, identifier, target_id)
    if interface.ipv4_address is None:
        raise PreconditionConflictError("interface has no IPv4 configuration")
    interface.ipv4_address = None
    interface.ipv4_prefix_length = None
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.CONFIGURATION,
        change_kinds=[ChangeKind.INTERFACE_IPV4_CLEARED],
        affected_entity_ids=[target_id],
        action_kind="INTERFACE_IPV4_CLEARED",
        entity_type="interface",
        entity_id=target_id,
        detail={},
    )
    return interface


def set_host_gateway(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    device_id: uuid.UUID | str,
    gateway_ipv4: str,
    actor: str = DEFAULT_ACTOR,
) -> Device:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(device_id, "device_id")
    validate_special_address(gateway_ipv4, "gateway_ipv4", role="gateway")
    value = ipv4_to_int(gateway_ipv4)
    project = _lock(session, identifier)
    device = _get_device(session, identifier, target_id)
    if device.kind not in (DeviceKind.PC, DeviceKind.SERVER):
        raise PreconditionConflictError(
            "default_gateway_ipv4 is only permitted on PC and SERVER devices"
        )
    if device.default_gateway_ipv4 == value:
        raise PreconditionConflictError("gateway was not changed")
    device.default_gateway_ipv4 = value
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.CONFIGURATION,
        change_kinds=[ChangeKind.HOST_GATEWAY_CONFIGURED],
        affected_entity_ids=[target_id],
        action_kind="HOST_GATEWAY_CONFIGURED",
        entity_type="device",
        entity_id=target_id,
        detail={"gateway_ipv4": gateway_ipv4},
    )
    return device


def clear_host_gateway(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    device_id: uuid.UUID | str,
    actor: str = DEFAULT_ACTOR,
) -> Device:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(device_id, "device_id")
    project = _lock(session, identifier)
    device = _get_device(session, identifier, target_id)
    if device.default_gateway_ipv4 is None:
        raise PreconditionConflictError("device has no default gateway")
    device.default_gateway_ipv4 = None
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.CONFIGURATION,
        change_kinds=[ChangeKind.HOST_GATEWAY_CLEARED],
        affected_entity_ids=[target_id],
        action_kind="HOST_GATEWAY_CLEARED",
        entity_type="device",
        entity_id=target_id,
        detail={},
    )
    return device


def move_device(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    device_id: uuid.UUID | str,
    position: Position,
    actor: str = DEFAULT_ACTOR,
) -> Device:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(device_id, "device_id")
    project = _lock(session, identifier)
    device = _get_device(session, identifier, target_id)
    new_position = (float(position.x), float(position.y), float(position.z))
    if (
        device.position_x,
        device.position_y,
        device.position_z,
    ) == new_position:
        raise PreconditionConflictError("device position was not changed")
    device.position_x, device.position_y, device.position_z = new_position
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.PRESENTATION,
        change_kinds=[ChangeKind.DEVICE_MOVED],
        affected_entity_ids=[target_id],
        action_kind="DEVICE_MOVED",
        entity_type="device",
        entity_id=target_id,
        detail={"position": {"x": position.x, "y": position.y, "z": position.z}},
    )
    return device


def rotate_device(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    device_id: uuid.UUID | str,
    rotation_y_degrees: float,
    actor: str = DEFAULT_ACTOR,
) -> Device:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(device_id, "device_id")
    angle = float(rotation_y_degrees)
    if not -180.0 <= angle < 180.0:
        raise PreconditionConflictError("rotation_y_degrees must be in [-180, 180)")
    project = _lock(session, identifier)
    device = _get_device(session, identifier, target_id)
    if device.rotation_y_degrees == angle:
        raise PreconditionConflictError("device rotation was not changed")
    device.rotation_y_degrees = angle
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.PRESENTATION,
        change_kinds=[ChangeKind.DEVICE_MOVED],
        affected_entity_ids=[target_id],
        action_kind="DEVICE_ROTATED",
        entity_type="device",
        entity_id=target_id,
        detail={"rotation_y_degrees": angle},
    )
    return device


def add_connection(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    interface_a_id: uuid.UUID | str,
    interface_b_id: uuid.UUID | str,
    cable_type: CableType | str = CableType.GENERIC_ETHERNET,
    actor: str = DEFAULT_ACTOR,
) -> ConnectionModel:
    identifier = _as_uuid(project_id, "project_id")
    endpoint_a = _as_uuid(interface_a_id, "interface_a_id")
    endpoint_b = _as_uuid(interface_b_id, "interface_b_id")
    cable = _require_kind(cable_type, CableType, "cable_type")
    if endpoint_a == endpoint_b:
        raise PreconditionConflictError("a connection needs two distinct interfaces")

    project = _lock(session, identifier)
    first = _get_interface(session, identifier, endpoint_a)
    second = _get_interface(session, identifier, endpoint_b)
    if first.device_id == second.device_id:
        raise PreconditionConflictError("an interface cannot connect to itself")
    first_device = _get_device(session, identifier, first.device_id)
    second_device = _get_device(session, identifier, second.device_id)
    if not cable_type_allowed(first_device.kind, second_device.kind, cable):
        raise IntegrityConflictError(
            f"cable {_entity_type(cable)} is not compatible with "
            f"{_entity_type(first_device.kind)} and "
            f"{_entity_type(second_device.kind)} interfaces"
        )
    # TASK-04 canonical endpoint order: lexicographically smaller interface_id first.
    if str(first.interface_id) <= str(second.interface_id):
        interface_a, interface_b = first, second
    else:
        interface_a, interface_b = second, first

    connection = ConnectionModel(
        connection_id=uuid7(),
        project_id=identifier,
        interface_a_id=interface_a.interface_id,
        interface_b_id=interface_b.interface_id,
        cable_type=cable,
        connection_sequence=project.next_connection_sequence,
        created_at=utc_now(),
    )
    project.next_connection_sequence += 1
    session.add(connection)
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.CONNECTION_ADDED],
        affected_entity_ids=[connection.connection_id],
        action_kind="CONNECTION_ADDED",
        entity_type="connection",
        entity_id=connection.connection_id,
        detail={
            "interface_a_id": str(connection.interface_a_id),
            "interface_b_id": str(connection.interface_b_id),
            "cable_type": _entity_type(cable),
        },
    )
    return connection


def remove_connection(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    connection_id: uuid.UUID | str,
    actor: str = DEFAULT_ACTOR,
) -> None:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(connection_id, "connection_id")
    project = _lock(session, identifier)
    connection = session.scalars(
        select(ConnectionModel).where(
            ConnectionModel.project_id == identifier,
            ConnectionModel.connection_id == target_id,
        )
    ).one_or_none()
    if connection is None:
        raise PreconditionConflictError(f"connection {target_id} is not in project {identifier}")
    session.delete(connection)
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.CONNECTION_REMOVED],
        affected_entity_ids=[target_id],
        action_kind="CONNECTION_REMOVED",
        entity_type="connection",
        entity_id=target_id,
        detail={},
    )


# ---------------------------------------------------------------------------
# Static routes
# ---------------------------------------------------------------------------


def _get_route(session: Session, project_id: uuid.UUID, route_id: uuid.UUID) -> StaticRoute:
    route = session.scalars(
        select(StaticRoute).where(
            StaticRoute.project_id == project_id, StaticRoute.route_id == route_id
        )
    ).one_or_none()
    if route is None:
        raise PreconditionConflictError(f"static route {route_id} is not in project {project_id}")
    return route


def add_static_route(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    router_device_id: uuid.UUID | str,
    destination_network: str,
    prefix_length: int,
    next_hop_ipv4: str,
    actor: str = DEFAULT_ACTOR,
) -> StaticRoute:
    identifier = _as_uuid(project_id, "project_id")
    router_id = _as_uuid(router_device_id, "router_device_id")
    prefix = _validate_prefix(prefix_length, minimum=0, maximum=32, field="prefix_length")
    destination = _network_aligned(destination_network, prefix)
    validate_special_address(next_hop_ipv4, "next_hop_ipv4", role="next_hop")
    next_hop = ipv4_to_int(next_hop_ipv4)

    project = _lock(session, identifier)
    router = _get_device(session, identifier, router_id)
    if router.kind is not DeviceKind.ROUTER:
        raise PreconditionConflictError("static routes belong to ROUTER devices only")
    duplicate = session.scalars(
        select(StaticRoute.route_id).where(
            StaticRoute.project_id == identifier,
            StaticRoute.router_device_id == router_id,
            StaticRoute.destination_network == destination,
            StaticRoute.prefix_length == prefix,
        )
    ).first()
    if duplicate is not None:
        raise IntegrityConflictError("an equivalent static route already exists")

    sequence = router.next_route_sequence
    if sequence is None:
        sequence = 1
    route = StaticRoute(
        route_id=uuid7(),
        project_id=identifier,
        router_device_id=router_id,
        destination_network=destination,
        prefix_length=prefix,
        next_hop_ipv4=next_hop,
        route_sequence=sequence,
        created_at=utc_now(),
    )
    router.next_route_sequence = sequence + 1
    session.add(route)
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.STATIC_ROUTE_ADDED],
        affected_entity_ids=[route.route_id],
        action_kind="STATIC_ROUTE_ADDED",
        entity_type="static_route",
        entity_id=route.route_id,
        detail={
            "destination_network": destination_network,
            "prefix_length": prefix,
            "next_hop_ipv4": next_hop_ipv4,
            "route_sequence": sequence,
        },
    )
    return route


def edit_static_route(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    route_id: uuid.UUID | str,
    destination_network: str | None = None,
    prefix_length: int | None = None,
    next_hop_ipv4: str | None = None,
    actor: str = DEFAULT_ACTOR,
) -> StaticRoute:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(route_id, "route_id")
    if next_hop_ipv4 is not None:
        validate_special_address(next_hop_ipv4, "next_hop_ipv4", role="next_hop")
    project = _lock(session, identifier)
    route = _get_route(session, identifier, target_id)

    new_destination = route.destination_network
    new_prefix = route.prefix_length
    new_next_hop = route.next_hop_ipv4
    if destination_network is not None:
        new_prefix = route.prefix_length if prefix_length is None else prefix_length
        new_prefix = _validate_prefix(new_prefix, minimum=0, maximum=32, field="prefix_length")
        new_destination = _network_aligned(destination_network, new_prefix)
    elif prefix_length is not None:
        new_prefix = _validate_prefix(prefix_length, minimum=0, maximum=32, field="prefix_length")
        new_destination = (
            route.destination_network & (((1 << 32) - 1) ^ ((1 << (32 - new_prefix)) - 1))
            if new_prefix > 0
            else route.destination_network
        )
    if next_hop_ipv4 is not None:
        new_next_hop = ipv4_to_int(next_hop_ipv4)

    duplicate = session.scalars(
        select(StaticRoute.route_id).where(
            StaticRoute.project_id == identifier,
            StaticRoute.router_device_id == route.router_device_id,
            StaticRoute.destination_network == new_destination,
            StaticRoute.prefix_length == new_prefix,
            StaticRoute.route_id != target_id,
        )
    ).first()
    if duplicate is not None:
        raise IntegrityConflictError("an equivalent static route already exists")

    if (
        new_destination == route.destination_network
        and new_prefix == route.prefix_length
        and new_next_hop == route.next_hop_ipv4
    ):
        raise PreconditionConflictError("static route was not changed")

    route.destination_network = new_destination
    route.prefix_length = new_prefix
    route.next_hop_ipv4 = new_next_hop
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.STATIC_ROUTE_EDITED],
        affected_entity_ids=[target_id],
        action_kind="STATIC_ROUTE_EDITED",
        entity_type="static_route",
        entity_id=target_id,
        detail={},
    )
    return route


def delete_static_route(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    route_id: uuid.UUID | str,
    actor: str = DEFAULT_ACTOR,
) -> None:
    identifier = _as_uuid(project_id, "project_id")
    target_id = _as_uuid(route_id, "route_id")
    project = _lock(session, identifier)
    route = _get_route(session, identifier, target_id)
    session.delete(route)
    session.flush()
    _commit_mutation(
        session,
        project,
        actor=actor,
        change_class=ChangeClass.TOPOLOGY,
        change_kinds=[ChangeKind.STATIC_ROUTE_DELETED],
        affected_entity_ids=[target_id],
        action_kind="STATIC_ROUTE_DELETED",
        entity_type="static_route",
        entity_id=target_id,
        detail={},
    )


def list_revisions(session: Session, project_id: uuid.UUID | str) -> list[ProjectRevision]:
    identifier = _as_uuid(project_id, "project_id")
    read_project(session, identifier)
    return list(
        session.scalars(
            select(ProjectRevision)
            .where(ProjectRevision.project_id == identifier)
            .order_by(ProjectRevision.revision)
        )
    )


__all__ = [
    "Position",
    "create_project",
    "open_project",
    "save_project",
    "list_checkpoints",
    "rename_device",
    "delete_project",
    "add_device",
    "remove_device",
    "set_interface_admin_state",
    "configure_interface_ipv4",
    "clear_interface_ipv4",
    "set_host_gateway",
    "clear_host_gateway",
    "move_device",
    "rotate_device",
    "add_connection",
    "remove_connection",
    "add_static_route",
    "edit_static_route",
    "delete_static_route",
    "list_revisions",
    "normalize_name",
]
