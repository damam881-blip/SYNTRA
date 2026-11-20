"""Ping, error and retention evidence tests for TASK-06."""

from __future__ import annotations

import hashlib

from app.modules.logs.service import (
    accept_ping_command,
    get_ping_result,
    load_retention_policy,
    purge_expired,
    record_error_envelope,
    record_ping_result,
)
from app.modules.projects.service import create_project


def _make_result(command, snapshot=None):
    if snapshot is None:
        snapshot = None
    base_state = 1
    base_sim = 1
    digest = "0" * 64
    if snapshot is not None:
        base_state = snapshot.base_state_revision
        base_sim = snapshot.base_simulation_revision
        digest = snapshot.configuration_digest
    return {
        "contract_version": "1.0.0",
        "test_id": str(command.test_id),
        "project_id": str(command.project_id),
        "source_device_id": str(command.source_device_id),
        "destination_device_id": str(command.destination_device_id),
        "snapshot_ref": {
            "project_id": str(command.project_id),
            "snapshot_id": str(command.snapshot_id),
            "base_state_revision": base_state,
            "base_simulation_revision": base_sim,
            "schema_version": "1.0.0",
            "configuration_digest": digest,
        },
        "lifecycle": "CLOSED",
        "execution_status": "COMPLETED",
        "aggregate_outcome": "SUCCESS",
        "observation_status": "COMPLETE",
        "started_at_ns": 0,
        "finalized_at_ns": 1,
        "closed_at_ns": 1,
        "statistics": {},
        "request_results": [],
        "diagnostics": [],
        "events": [],
        "hop_evidence": [],
        "derived_warning_evidence": [],
    }


def test_accept_and_record_ping_result(session):
    project = create_project(session, name="Lab 1")
    pc1 = __import__(
        "app.modules.projects.service", fromlist=["add_device"]
    ).add_device(session, project.project_id, kind="PC", display_name="PC1")
    pc2 = __import__(
        "app.modules.projects.service", fromlist=["add_device"]
    ).add_device(session, project.project_id, kind="PC", display_name="PC2")
    session.commit()
    command = accept_ping_command(
        session,
        project.project_id,
        source_device_id=pc1.device_id,
        destination_device_id=pc2.device_id,
    )
    session.commit()
    from app.db.models import SnapshotRef

    snapshot = session.get(SnapshotRef, command.snapshot_id)
    result = _make_result(command)
    result["snapshot_ref"] = {
        "project_id": str(command.project_id),
        "snapshot_id": str(command.snapshot_id),
        "base_state_revision": snapshot.base_state_revision,
        "base_simulation_revision": snapshot.base_simulation_revision,
        "schema_version": "1.0.0",
        "configuration_digest": snapshot.configuration_digest,
    }
    result = record_ping_result(session, result)
    session.commit()
    stored = get_ping_result(session, command.test_id)
    assert stored.result_sha256 == result.result_sha256
    # canonical bytes round-trip
    recomputed = hashlib.sha256(stored.canonical_json.encode("utf-8")).hexdigest()
    assert recomputed == stored.result_sha256


def test_error_envelope_and_log_consistency(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    envelope = record_error_envelope(
        session,
        {
            "contract_version": "1.0.0",
            "project_id": str(project.project_id),
            "error_class": "PERSISTENCE_FAILURE",
            "code": "PERSISTENCE_UNAVAILABLE",
            "message_key": "persistence.failed",
            "details": [{"x": 1}],
        },
    )
    session.commit()
    assert envelope.error_id is not None


def test_retention_purge_runs(session):
    policy = load_retention_policy(session)
    assert policy.policy_name == "default"
    counts = purge_expired(session)
    session.commit()
    assert set(counts) == {
        "action_log",
        "ping_log",
        "error_log",
        "ping_result",
        "snapshot_ref",
        "error_envelope",
    }
