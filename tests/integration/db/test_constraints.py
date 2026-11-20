"""Database-level invariant tests for TASK-06."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.base import uuid7
from app.db.models import (
    Connection,
    Device,
    ErrorEnvelope,
    Interface,
    PingTestCommand,
    PingTestResult,
    Project,
    ProjectRevision,
    SnapshotRef,
)


def _project(session):
    project = Project(
        project_id=uuid7(),
        name="Constraint Lab",
        state_revision=1,
        simulation_revision=1,
        next_device_sequence=1,
        next_mac_sequence=1,
        next_connection_sequence=1,
    )
    session.add(project)
    session.flush()
    return project


def test_immutable_revision_rejects_update(session):
    project = _project(session)
    session.add(
        ProjectRevision(
            project_id=project.project_id,
            revision=1,
            change_class="TOPOLOGY",
            change_kinds=["PROJECT_CREATED"],
            affected_entity_ids=[project.project_id],
        )
    )
    session.flush()
    with pytest.raises(IntegrityError):
        session.execute(
            __import__("sqlalchemy").text(
                "update project_revision set change_class='METADATA' "
                "where project_id=:p and revision=1"
            ),
            {"p": project.project_id},
        )
        session.flush()


def test_connection_occupancy_rejects_duplicate(session):
    project = _project(session)
    d1 = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="PC",
        display_name="PC1",
        normalized_name="pc1",
        device_sequence=1,
        next_route_sequence=None,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
    )
    d2 = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="PC",
        display_name="PC2",
        normalized_name="pc2",
        device_sequence=2,
        next_route_sequence=None,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
    )
    session.add_all([d1, d2])
    session.flush()
    if1 = Interface(
        interface_id=uuid7(),
        project_id=project.project_id,
        device_id=d1.device_id,
        display_name="FastEthernet0",
        ordinal=0,
        interface_kind="FAST_ETHERNET",
        admin_state="ENABLED",
        mac_address="02:00:00:00:00:01",
        mac_sequence=1,
    )
    if2 = Interface(
        interface_id=uuid7(),
        project_id=project.project_id,
        device_id=d2.device_id,
        display_name="FastEthernet0",
        ordinal=0,
        interface_kind="FAST_ETHERNET",
        admin_state="ENABLED",
        mac_address="02:00:00:00:00:02",
        mac_sequence=2,
    )
    session.add_all([if1, if2])
    session.flush()
    a_id, b_id = sorted([if1.interface_id, if2.interface_id], key=lambda x: str(x))
    session.add(
        Connection(
            connection_id=uuid7(),
            project_id=project.project_id,
            interface_a_id=a_id,
            interface_b_id=b_id,
            cable_type="GENERIC_ETHERNET",
            connection_sequence=1,
        )
    )
    session.flush()
    with pytest.raises(IntegrityError):
        session.add(
            Connection(
                connection_id=uuid7(),
                project_id=project.project_id,
                interface_a_id=a_id,
                interface_b_id=b_id,
                cable_type="GENERIC_ETHERNET",
                connection_sequence=2,
            )
        )
        session.flush()


def test_switch_ipv4_rejected(session):
    project = _project(session)
    device = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="L2_SWITCH",
        display_name="SW1",
        normalized_name="sw1",
        device_sequence=1,
        next_route_sequence=None,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
    )
    session.add(device)
    session.flush()
    interface = Interface(
        interface_id=uuid7(),
        project_id=project.project_id,
        device_id=device.device_id,
        display_name="FastEthernet0/1",
        ordinal=0,
        interface_kind="FAST_ETHERNET",
        admin_state="ENABLED",
        mac_address="02:00:00:00:00:01",
        mac_sequence=1,
        ipv4_address=167772161,
        ipv4_prefix_length=24,
    )
    session.add(interface)
    with pytest.raises(IntegrityError):
        session.flush()


def test_host_gateway_rejected_on_router(session):
    project = _project(session)
    device = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="ROUTER",
        display_name="R1",
        normalized_name="r1",
        device_sequence=1,
        next_route_sequence=1,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
        default_gateway_ipv4=167772161,
    )
    session.add(device)
    with pytest.raises(IntegrityError):
        session.flush()


def test_revision_gaplessness_rejects_gap(session):
    project = _project(session)
    session.add(
        ProjectRevision(
            project_id=project.project_id,
            revision=3,
            change_class="TOPOLOGY",
            change_kinds=["PROJECT_CREATED"],
            affected_entity_ids=[project.project_id],
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_snapshot_revision_consistency_rejects_mismatch(session):
    project = _project(session)
    with pytest.raises(IntegrityError):
        session.add(
            SnapshotRef(
                snapshot_id=uuid7(),
                project_id=project.project_id,
                base_state_revision=99,
                base_simulation_revision=1,
                schema_version="1.0.0",
                configuration_digest=__import__("hashlib").sha256(b"{}").hexdigest(),
                configuration_json={},
                canonical_json="{}",
            )
        )
        session.flush()


def test_ping_endpoint_validation_rejects_router(session):
    project = _project(session)
    router = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="ROUTER",
        display_name="R1",
        normalized_name="r1",
        device_sequence=1,
        next_route_sequence=1,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
    )
    session.add(router)
    session.flush()
    with pytest.raises(IntegrityError):
        session.add(
            PingTestCommand(
                command_id=uuid7(),
                contract_version="1.0.0",
                test_id=uuid7(),
                project_id=project.project_id,
                source_device_id=router.device_id,
                destination_device_id=router.device_id,
                test_kind="PING",
                expected_echo_requests=4,
                initial_runtime_state="FRESH",
                snapshot_id=uuid7(),
            )
        )
        session.flush()


def test_ping_result_hash_mismatch_rejected(session):
    project = _project(session)
    pc1 = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="PC",
        display_name="PC1",
        normalized_name="pc1",
        device_sequence=1,
        next_route_sequence=None,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
    )
    pc2 = Device(
        device_id=uuid7(),
        project_id=project.project_id,
        kind="PC",
        display_name="PC2",
        normalized_name="pc2",
        device_sequence=2,
        next_route_sequence=None,
        position_x=0,
        position_y=0,
        position_z=0,
        rotation_y_degrees=0,
    )
    session.add_all([pc1, pc2])
    session.flush()
    snapshot = SnapshotRef(
        snapshot_id=uuid7(),
        project_id=project.project_id,
        base_state_revision=1,
        base_simulation_revision=1,
        schema_version="1.0.0",
        configuration_digest=__import__("hashlib").sha256(b"{}").hexdigest(),
        configuration_json={},
        canonical_json="{}",
    )
    # snapshot revisions must match project current revisions; fix counters.
    project.state_revision = 1
    session.add(snapshot)
    session.flush()
    # The snapshot digest trigger would reject a wrong digest; bypass by
    # re-hashing the actual canonical bytes.
    snapshot.configuration_digest = __import__("hashlib").sha256(b"{}").hexdigest()
    session.flush()
    command = PingTestCommand(
        command_id=uuid7(),
        contract_version="1.0.0",
        test_id=uuid7(),
        project_id=project.project_id,
        source_device_id=pc1.device_id,
        destination_device_id=pc2.device_id,
        test_kind="PING",
        expected_echo_requests=4,
        initial_runtime_state="FRESH",
        snapshot_id=snapshot.snapshot_id,
    )
    session.add(command)
    session.flush()
    with pytest.raises(IntegrityError):
        session.add(
            PingTestResult(
                test_id=command.test_id,
                contract_version="1.0.0",
                project_id=project.project_id,
                source_device_id=pc1.device_id,
                destination_device_id=pc2.device_id,
                snapshot_id=snapshot.snapshot_id,
                lifecycle="CLOSED",
                execution_status="COMPLETED",
                observation_status="COMPLETE",
                started_at_ns=0,
                finalized_at_ns=1,
                closed_at_ns=1,
                statistics_json={},
                request_results_json=[],
                diagnostics_json=[],
                events_json=[],
                hop_evidence_json=[],
                derived_warning_evidence_json=[],
                canonical_json="{}",
                result_sha256="f" * 64,
            )
        )
        session.flush()


def test_error_snapshot_project_consistency(session):
    project = _project(session)
    with pytest.raises(IntegrityError):
        session.add(
            ErrorEnvelope(
                error_id=uuid7(),
                contract_version="1.0.0",
                project_id=project.project_id,
                error_class="PERSISTENCE_FAILURE",
                code="PERSISTENCE_UNAVAILABLE",
                message_key="persistence.failed",
                details_json=[],
                snapshot_id=uuid7(),
                retryable=False,
                canonical_json="{}",
                canonical_sha256=__import__("hashlib").sha256(b"{}").hexdigest(),
            )
        )
        session.flush()
