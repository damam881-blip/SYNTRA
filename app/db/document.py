"""Canonical TASK-04 ProjectStateDocument serialisation and configuration digest.

The relational tables are the committed aggregate; this module renders that
aggregate back into the approved TASK-04 v1.0.0 document so it can be handed to
TASK-05, to the API layer, or frozen into a simulation snapshot.

The digest is computed with the *exact* projection defined by the approved
reference implementation
(``contracts/reference/task04/tools/configuration_digest.py``):

* devices ordered by ``device_sequence``;
* interfaces ordered by ``(device_sequence, ordinal)``;
* connections ordered by ``connection_sequence``;
* static routes ordered by ``(router device_sequence, route_sequence)``;
* presentation fields (position, rotation), project text, checkpoints and the
  revision history are excluded.

Any change to this module must keep the five values in
``contracts/reference/task04/fixtures/digests.json`` reproducible.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import int_to_ipv4
from app.db.errors import ProjectNotFoundError
from app.db.models import (
    Checkpoint,
    Connection,
    Device,
    Interface,
    Project,
    ProjectRevision,
    StaticRoute,
)

MODEL_SCHEMA_VERSION = "1.0.0"


def iso_timestamp(value: datetime) -> str:
    """Render an RFC 3339 UTC timestamp with millisecond precision and ``Z``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    utc = value.astimezone(UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def _value(member: Any) -> Any:
    """Unwrap StrEnum members to their approved wire spelling."""
    return member.value if hasattr(member, "value") else member


def lock_project(session: Session, project_id: uuid.UUID) -> Project:
    """Fetch a project while holding a row lock for the rest of the transaction.

    Writers use ``FOR UPDATE``; consistent readers use :func:`read_project` with
    ``FOR SHARE`` so a multi-table read can never interleave with a commit.
    """
    project = session.scalars(
        select(Project).where(Project.project_id == project_id).with_for_update()
    ).one_or_none()
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} does not exist")
    return project


def read_project(session: Session, project_id: uuid.UUID) -> Project:
    """Fetch a project under a shared lock for a consistent multi-table read."""
    project = session.scalars(
        select(Project).where(Project.project_id == project_id).with_for_update(read=True)
    ).one_or_none()
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} does not exist")
    return project


def project_document(
    session: Session,
    project_id: uuid.UUID,
    *,
    consistent_read: bool = True,
) -> dict[str, Any]:
    """Render the canonical TASK-04 document for ``project_id``.

    With ``consistent_read`` the project row is locked in SHARE mode first, so
    devices, interfaces, connections, routes, revisions and checkpoints are all
    observed at one committed revision.
    """
    project = (
        read_project(session, project_id) if consistent_read else session.get(Project, project_id)
    )
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} does not exist")

    devices = list(
        session.scalars(
            select(Device).where(Device.project_id == project_id).order_by(Device.device_sequence)
        )
    )
    interfaces = list(
        session.scalars(
            select(Interface)
            .where(Interface.project_id == project_id)
            .order_by(Interface.device_id, Interface.ordinal)
        )
    )
    connections = list(
        session.scalars(
            select(Connection)
            .where(Connection.project_id == project_id)
            .order_by(Connection.connection_sequence)
        )
    )
    routes = list(
        session.scalars(
            select(StaticRoute)
            .where(StaticRoute.project_id == project_id)
            .order_by(StaticRoute.router_device_id, StaticRoute.route_sequence)
        )
    )
    revisions = list(
        session.scalars(
            select(ProjectRevision)
            .where(ProjectRevision.project_id == project_id)
            .order_by(ProjectRevision.revision)
        )
    )
    checkpoints = list(
        session.scalars(
            select(Checkpoint)
            .where(Checkpoint.project_id == project_id)
            .order_by(Checkpoint.created_at, Checkpoint.checkpoint_id)
        )
    )

    device_sequence = {device.device_id: device.device_sequence for device in devices}
    interfaces.sort(key=lambda i: (device_sequence[i.device_id], i.ordinal))
    routes.sort(key=lambda r: (device_sequence[r.router_device_id], r.route_sequence))

    document: dict[str, Any] = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "project": _project_payload(project),
        "devices": [_device_payload(device) for device in devices],
        "interfaces": [_interface_payload(interface) for interface in interfaces],
        "connections": [_connection_payload(connection) for connection in connections],
        "static_routes": [_route_payload(route) for route in routes],
        "revisions": [_revision_payload(revision) for revision in revisions],
    }
    if checkpoints:
        document["checkpoints"] = [_checkpoint_payload(checkpoint) for checkpoint in checkpoints]
    return document


def _project_payload(project: Project) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": str(project.project_id),
        "name": project.name,
        "state_revision": project.state_revision,
        "simulation_revision": project.simulation_revision,
        "next_device_sequence": project.next_device_sequence,
        "next_mac_sequence": project.next_mac_sequence,
        "next_connection_sequence": project.next_connection_sequence,
        "created_at": iso_timestamp(project.created_at),
        "updated_at": iso_timestamp(project.updated_at),
    }
    if project.description is not None:
        payload["description"] = project.description
    return payload


def _device_payload(device: Device) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": str(device.device_id),
        "kind": _value(device.kind),
        "display_name": device.display_name,
        "normalized_name": device.normalized_name,
        "device_sequence": device.device_sequence,
        "position": {
            "x": device.position_x,
            "y": device.position_y,
            "z": device.position_z,
        },
        "rotation_y_degrees": device.rotation_y_degrees,
        "created_at": iso_timestamp(device.created_at),
    }
    if device.default_gateway_ipv4 is not None:
        payload["default_gateway_ipv4"] = int_to_ipv4(device.default_gateway_ipv4)
    if device.next_route_sequence is not None:
        payload["next_route_sequence"] = device.next_route_sequence
    return payload


def _interface_payload(interface: Interface) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "interface_id": str(interface.interface_id),
        "device_id": str(interface.device_id),
        "display_name": interface.display_name,
        "ordinal": interface.ordinal,
        "interface_kind": _value(interface.interface_kind),
        "admin_state": _value(interface.admin_state),
        "mac_address": interface.mac_address,
        "mac_sequence": interface.mac_sequence,
    }
    if interface.ipv4_address is not None:
        payload["ipv4"] = {
            "address": int_to_ipv4(interface.ipv4_address),
            "prefix_length": interface.ipv4_prefix_length,
        }
    return payload


def _connection_payload(connection: Connection) -> dict[str, Any]:
    return {
        "connection_id": str(connection.connection_id),
        "interface_a_id": str(connection.interface_a_id),
        "interface_b_id": str(connection.interface_b_id),
        "cable_type": _value(connection.cable_type),
        "connection_sequence": connection.connection_sequence,
        "created_at": iso_timestamp(connection.created_at),
    }


def _route_payload(route: StaticRoute) -> dict[str, Any]:
    return {
        "route_id": str(route.route_id),
        "router_device_id": str(route.router_device_id),
        "destination_network": int_to_ipv4(route.destination_network),
        "prefix_length": route.prefix_length,
        "next_hop_ipv4": int_to_ipv4(route.next_hop_ipv4),
        "route_sequence": route.route_sequence,
        "created_at": iso_timestamp(route.created_at),
    }


def _revision_payload(revision: ProjectRevision) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "revision": revision.revision,
        "change_class": _value(revision.change_class),
        "change_kinds": list(revision.change_kinds),
        "committed_at": iso_timestamp(revision.committed_at),
    }
    if revision.affected_entity_ids:
        payload["affected_entity_ids"] = [
            str(entity_id) for entity_id in revision.affected_entity_ids
        ]
    return payload


def _checkpoint_payload(checkpoint: Checkpoint) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "checkpoint_id": str(checkpoint.checkpoint_id),
        "revision": checkpoint.revision,
        "created_at": iso_timestamp(checkpoint.created_at),
    }
    if checkpoint.label is not None:
        payload["label"] = checkpoint.label
    return payload


def configuration_projection(document: dict[str, Any]) -> dict[str, Any]:
    """Return the approved TASK-04 section 7.4 behavioural projection."""
    devices = sorted(document["devices"], key=lambda d: d["device_sequence"])
    order = {device["device_id"]: device["device_sequence"] for device in devices}
    interfaces = sorted(document["interfaces"], key=lambda i: (order[i["device_id"]], i["ordinal"]))
    routes = sorted(
        document["static_routes"],
        key=lambda r: (order[r["router_device_id"]], r["route_sequence"]),
    )
    return {
        "schema_version": document["schema_version"],
        "project": {"project_id": document["project"]["project_id"]},
        "devices": [
            {
                "device_id": device["device_id"],
                "kind": device["kind"],
                "device_sequence": device["device_sequence"],
                "default_gateway_ipv4": device.get("default_gateway_ipv4"),
            }
            for device in devices
        ],
        "interfaces": [
            {
                "interface_id": interface["interface_id"],
                "device_id": interface["device_id"],
                "ordinal": interface["ordinal"],
                "interface_kind": interface["interface_kind"],
                "admin_state": interface["admin_state"],
                "mac_address": interface["mac_address"],
                "mac_sequence": interface["mac_sequence"],
                "ipv4": interface.get("ipv4"),
            }
            for interface in interfaces
        ],
        "connections": [
            {
                "connection_id": connection["connection_id"],
                "interface_a_id": connection["interface_a_id"],
                "interface_b_id": connection["interface_b_id"],
                "cable_type": connection["cable_type"],
                "connection_sequence": connection["connection_sequence"],
            }
            for connection in sorted(
                document["connections"], key=lambda c: c["connection_sequence"]
            )
        ],
        "static_routes": [
            {
                "route_id": route["route_id"],
                "router_device_id": route["router_device_id"],
                "destination_network": route["destination_network"],
                "prefix_length": route["prefix_length"],
                "next_hop_ipv4": route["next_hop_ipv4"],
                "route_sequence": route["route_sequence"],
            }
            for route in routes
        ],
    }


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    """Canonical UTF-8 bytes of the configuration projection."""
    payload = configuration_projection(document)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def canonical_json_text(document: dict[str, Any]) -> str:
    return canonical_json_bytes(document).decode("utf-8")


def configuration_digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()
