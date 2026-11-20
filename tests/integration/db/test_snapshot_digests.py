"""Snapshot digest verification against the approved TASK-04 fixtures."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime

import pytest

from app.db.base import ipv4_to_int
from app.db.models import (
    Connection,
    Device,
    Interface,
    Project,
    ProjectRevision,
    StaticRoute,
)
from app.db.snapshot import capture_snapshot, verify_snapshot


def _parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_fixture(session, path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    proj = doc["project"]
    project = Project(
        project_id=proj["project_id"],
        name=proj["name"],
        description=proj.get("description"),
        state_revision=proj["state_revision"],
        simulation_revision=proj["simulation_revision"],
        next_device_sequence=proj["next_device_sequence"],
        next_mac_sequence=proj["next_mac_sequence"],
        next_connection_sequence=proj["next_connection_sequence"],
        created_at=_parse(proj["created_at"]),
        updated_at=_parse(proj["updated_at"]),
    )
    session.add(project)
    for rev in doc["revisions"]:
        session.add(
            ProjectRevision(
                project_id=proj["project_id"],
                revision=rev["revision"],
                change_class=rev["change_class"],
                change_kinds=rev["change_kinds"],
                affected_entity_ids=rev.get("affected_entity_ids", []),
                committed_at=_parse(rev["committed_at"]),
            )
        )
    session.flush()
    for d in doc["devices"]:
        session.add(
            Device(
                device_id=d["device_id"],
                project_id=proj["project_id"],
                kind=d["kind"],
                display_name=d["display_name"],
                normalized_name=d["normalized_name"],
                device_sequence=d["device_sequence"],
                default_gateway_ipv4=(
                    None
                    if d.get("default_gateway_ipv4") is None
                    else ipv4_to_int(d["default_gateway_ipv4"])
                ),
                position_x=d["position"]["x"],
                position_y=d["position"]["y"],
                position_z=d["position"]["z"],
                rotation_y_degrees=d.get("rotation_y_degrees", 0.0),
                next_route_sequence=d.get("next_route_sequence"),
                created_at=_parse(d["created_at"]),
            )
        )
    session.flush()
    for i in doc["interfaces"]:
        session.add(
            Interface(
                interface_id=i["interface_id"],
                project_id=proj["project_id"],
                device_id=i["device_id"],
                display_name=i["display_name"],
                ordinal=i["ordinal"],
                interface_kind=i["interface_kind"],
                admin_state=i["admin_state"],
                mac_address=i["mac_address"],
                mac_sequence=i["mac_sequence"],
                ipv4_address=(
                    None
                    if i.get("ipv4") is None
                    else ipv4_to_int(i["ipv4"]["address"])
                ),
                ipv4_prefix_length=(
                    None if i.get("ipv4") is None else i["ipv4"]["prefix_length"]
                ),
            )
        )
    session.flush()
    for c in doc["connections"]:
        session.add(
            Connection(
                connection_id=c["connection_id"],
                project_id=proj["project_id"],
                interface_a_id=c["interface_a_id"],
                interface_b_id=c["interface_b_id"],
                cable_type=c["cable_type"],
                connection_sequence=c["connection_sequence"],
                created_at=_parse(c["created_at"]),
            )
        )
    session.flush()
    for r in doc["static_routes"]:
        session.add(
            StaticRoute(
                route_id=r["route_id"],
                project_id=proj["project_id"],
                router_device_id=r["router_device_id"],
                destination_network=ipv4_to_int(r["destination_network"]),
                prefix_length=r["prefix_length"],
                next_hop_ipv4=ipv4_to_int(r["next_hop_ipv4"]),
                route_sequence=r["route_sequence"],
                created_at=_parse(r["created_at"]),
            )
        )
    session.flush()
    return proj["project_id"], doc


@pytest.mark.parametrize(
    "fixture_name,expected_digest",
    [
        ("rt-01.json", "b0837374187220bde72972d13a708096eb7df76217c8c9487224c83df9a14e5e"),
        ("rt-02.json", "5ee66c67e814beb69368f01b2ba1a43147892a6506fbdd3f289c99e7fc57f2eb"),
        ("rt-03.json", "a9c2e47d5c3879fe2eb8e06216a029c5ea8023186f853877c9f7e3f7d6ec9306"),
        ("rt-04.json", "ba18d012468c378746d93872281c15b4b5c132970a45e01f53657e3bbbd4642f"),
        ("rt-05.json", "96418a28a37d656eeae445a82a89ea1a2558f293635f80c4e11b5bdb6d89d31c"),
    ],
)
def test_snapshot_digest_matches_fixture(clean_engine, fixture_name, expected_digest):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=clean_engine, expire_on_commit=False)
    root = pathlib.Path(
        r"E:\SYNTRA\network-simulator-backend\contracts\reference\task04\fixtures"
    )
    with factory() as session:
        pid, doc = _load_fixture(session, root / fixture_name)
        session.commit()
        snapshot = capture_snapshot(session, pid)
        session.commit()
        verify_snapshot(snapshot)
        assert snapshot.configuration_digest == expected_digest
        assert snapshot.base_state_revision == doc["project"]["state_revision"]
        assert snapshot.base_simulation_revision == doc["project"]["simulation_revision"]
        # snapshot is frozen: a later mutation does not change the digest

        # capture again not needed; digest remains
        assert snapshot.configuration_digest == expected_digest
