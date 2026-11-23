"""Phase 4: end-to-end proof from a frozen snapshot to a verified TASK-05 result.

The snapshot object is built from a TASK-04 fixture with the real capture/digest
helpers. ``app.db.snapshot.replay_input`` is the API boundary; the runner receives
only its verified projection. No endpoint, persistence path or step-7 code is
exercised.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from app.db.document import canonical_json_bytes, configuration_digest, configuration_projection
from app.db.models import SnapshotRef
from app.db.snapshot import SnapshotIntegrityError, replay_input
from app.engine.ping import SimulatedPingRunner

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "reference" / "task04" / "fixtures"
TASK05 = ROOT / "contracts" / "reference" / "task05"
SNAPSHOT_ID = UUID("019a5000-0000-7000-8000-000000000004")
TEST_ID = UUID("019a5000-0000-7000-8000-000000000099")
SOURCE_IP = "192.168.10.10"

_SCHEMA = json.loads((TASK05 / "schemas" / "task05-contract-v1.schema.json").read_text())
SCHEMA_VALIDATOR = Draft202012Validator(_SCHEMA)


def _load_verifier() -> Any:
    path = TASK05 / "tools" / "verify_contract.py"
    spec = importlib.util.spec_from_file_location("task05_verify_contract_e2e", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_verifier()


def _snapshot(name: str) -> SnapshotRef:
    document = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return SnapshotRef(
        snapshot_id=SNAPSHOT_ID,
        project_id=UUID(document["project"]["project_id"]),
        base_state_revision=document["project"]["state_revision"],
        base_simulation_revision=document["project"]["simulation_revision"],
        schema_version="1.0.0",
        configuration_digest=configuration_digest(document),
        configuration_json=configuration_projection(document),
        canonical_json=canonical_json_bytes(document).decode("utf-8"),
    )


def _endpoints(replay: dict[str, Any]) -> tuple[str, str]:
    configuration = replay["configuration"]
    kinds = {device["device_id"]: device["kind"] for device in configuration["devices"]}
    endpoints = [
        interface["device_id"]
        for interface in configuration["interfaces"]
        if interface.get("ipv4") and kinds[interface["device_id"]] in ("PC", "SERVER")
    ]
    source = next(
        interface["device_id"]
        for interface in configuration["interfaces"]
        if (interface.get("ipv4") or {}).get("address") == SOURCE_IP
    )
    return source, endpoints[-1]


def _run_from_snapshot(snapshot: SnapshotRef) -> dict[str, object]:
    replay = replay_input(snapshot)
    source, destination = _endpoints(replay)
    result = SimulatedPingRunner().run(
        replay,
        test_id=TEST_ID,
        project_id=UUID(replay["configuration"]["project"]["project_id"]),
        source_device_id=UUID(source),
        destination_device_id=UUID(destination),
    )
    errors = [error.message for error in SCHEMA_VALIDATOR.iter_errors(result)]
    assert not errors, f"SCHEMA: {errors[:3]}"
    assert VERIFIER.check(result) == []
    assert result["snapshot_ref"]["snapshot_id"] == str(snapshot.snapshot_id)
    assert result["snapshot_ref"]["configuration_digest"] == snapshot.configuration_digest
    return result


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("rt-01", "SUCCESS"),
        ("rt-02", "SUCCESS"),
        ("rt-03", "SUCCESS"),
        ("rt-04", "SUCCESS"),
        ("rt-05", "FAILURE"),
    ],
)
def test_snapshot_to_result(fixture: str, expected: str) -> None:
    result = _run_from_snapshot(_snapshot(fixture))
    assert result["execution_status"] == "COMPLETED"
    assert result["aggregate_outcome"] == expected
    assert len(result["request_results"]) == 4
    assert result["events"]


def test_replay_input_is_isolated_from_snapshot() -> None:
    snapshot = _snapshot("rt-01")
    replay = replay_input(snapshot)
    replay["configuration"]["devices"][0]["__mutated__"] = True
    assert all("__mutated__" not in device for device in snapshot.configuration_json["devices"])


def test_snapshot_digest_tampering_is_rejected() -> None:
    snapshot = _snapshot("rt-01")
    snapshot.canonical_json = snapshot.canonical_json.replace("192.168.10", "192.168.11", 1)
    with pytest.raises(SnapshotIntegrityError):
        replay_input(snapshot)


def test_snapshot_replay_is_deterministic() -> None:
    snapshot = _snapshot("rt-04")
    assert _run_from_snapshot(snapshot) == _run_from_snapshot(snapshot)
