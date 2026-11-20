"""Ping, error and retention evidence tests for TASK-06."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.db.errors import ContractValidationError
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
    """Return a valid frozen-contract result, bound to the accepted command."""
    root = Path(__file__).resolve().parents[3]
    result = json.loads(
        (root / "contracts" / "reference" / "task05" / "examples" / "ping_success.json").read_text(
            encoding="utf-8"
        )
    )
    result.update(
        {
            "test_id": str(command.test_id),
            "project_id": str(command.project_id),
            "source_device_id": str(command.source_device_id),
            "destination_device_id": str(command.destination_device_id),
        }
    )
    if snapshot is not None:
        result["snapshot_ref"] = {
            "project_id": str(command.project_id),
            "snapshot_id": str(command.snapshot_id),
            "base_state_revision": snapshot.base_state_revision,
            "base_simulation_revision": snapshot.base_simulation_revision,
            "schema_version": "1.0.0",
            "configuration_digest": snapshot.configuration_digest,
        }
    return result


def test_accept_and_record_ping_result(session):
    project = create_project(session, name="Lab 1")
    pc1 = __import__("app.modules.projects.service", fromlist=["add_device"]).add_device(
        session, project.project_id, kind="PC", display_name="PC1"
    )
    pc2 = __import__("app.modules.projects.service", fromlist=["add_device"]).add_device(
        session, project.project_id, kind="PC", display_name="PC2"
    )
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
    result = _make_result(command, snapshot)
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
            "details": [
                {
                    "field_path": "database",
                    "reason_key": "persistence.unavailable",
                    "observed_value": None,
                }
            ],
        },
    )
    session.commit()
    assert envelope.error_id is not None


def test_ping_result_rejects_unknown_contract_field(session):
    project = create_project(session, name="Lab 1")
    pc1 = __import__("app.modules.projects.service", fromlist=["add_device"]).add_device(
        session, project.project_id, kind="PC", display_name="PC1"
    )
    pc2 = __import__("app.modules.projects.service", fromlist=["add_device"]).add_device(
        session, project.project_id, kind="PC", display_name="PC2"
    )
    session.commit()
    command = accept_ping_command(
        session,
        project.project_id,
        source_device_id=pc1.device_id,
        destination_device_id=pc2.device_id,
    )
    session.commit()
    from app.db.models import SnapshotRef

    result = _make_result(command, session.get(SnapshotRef, command.snapshot_id))
    result["unexpected"] = True
    with pytest.raises(ContractValidationError, match="Additional properties"):
        record_ping_result(session, result)


def test_error_envelope_rejects_invalid_detail_shape(session):
    with pytest.raises(ContractValidationError, match="TASK-05 ErrorEnvelope invalid"):
        record_error_envelope(
            session,
            {
                "contract_version": "1.0.0",
                "error_class": "PERSISTENCE_FAILURE",
                "code": "PERSISTENCE_UNAVAILABLE",
                "message_key": "persistence.failed",
                "details": [{"invalid": True}],
            },
        )


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
