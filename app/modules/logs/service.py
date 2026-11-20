"""Evidence persistence: accepted Ping commands, immutable TASK-05 results,
structured error envelopes and the retention policy.

Immutability is enforced twice: application code never issues UPDATE/DELETE on
the historical tables, and the database ``syntra_guard_immutable`` triggers
reject it outside ``syntra.purge_mode``.  Retention is the only path that may
remove evidence, and it runs with the documented purge flag.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from sqlalchemy import delete as sql_delete
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import utc_now, uuid7
from app.db.enums import (
    AggregateOutcome,
    ExecutionStatus,
    ObservationStatus,
)
from app.db.errors import (
    ContractValidationError,
    PreconditionConflictError,
    ProjectNotFoundError,
)
from app.db.models import (
    ActionLog,
    Device,
    ErrorEnvelope,
    ErrorLog,
    PingLog,
    PingTestCommand,
    PingTestResult,
    Project,
    RetentionPolicy,
    SnapshotRef,
)
from app.db.snapshot import capture_snapshot
from app.modules.projects.service import _lock, _log_action

CONTRACT_VERSION = "1.0.0"
DEFAULT_POLICY = "default"
RESULT_REQUIRED_FIELDS = (
    "contract_version",
    "test_id",
    "project_id",
    "source_device_id",
    "destination_device_id",
    "snapshot_ref",
    "lifecycle",
    "execution_status",
    "aggregate_outcome",
    "observation_status",
    "started_at_ns",
    "finalized_at_ns",
    "closed_at_ns",
    "statistics",
    "request_results",
    "diagnostics",
    "events",
    "hop_evidence",
    "derived_warning_evidence",
)


@lru_cache(maxsize=1)
def _task05_schema() -> dict[str, Any]:
    """Load the byte-preserved, approved TASK-05 reference schema."""
    path = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "reference"
        / "task05"
        / "schemas"
        / "task05-contract-v1.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _task05_validator(definition: str) -> jsonschema.Draft202012Validator:
    schema = _task05_schema()
    return jsonschema.Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$ref": f"#/$defs/{definition}",
            "$defs": schema["$defs"],
        }
    )


def _validate_task05_document(payload: dict[str, Any], definition: str) -> None:
    """Reject a document that is not exactly representable by the frozen contract."""
    errors = sorted(
        _task05_validator(definition).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise ContractValidationError(f"TASK-05 {definition} invalid at {location}: {error.message}")


def _as_uuid(value: uuid.UUID | str, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as error:
        raise ContractValidationError(f"{field} is not a valid UUID") from error


def canonical_contract_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic bytes used as the stored evidence contract."""
    text_value = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text_value.encode("utf-8")


def _require_result_fields(payload: dict[str, Any]) -> None:
    missing = [field for field in RESULT_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ContractValidationError(
            f"Ping result is missing required fields: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Ping commands and results
# ---------------------------------------------------------------------------


def accept_ping_command(
    session: Session,
    project_id: uuid.UUID | str,
    *,
    source_device_id: uuid.UUID | str,
    destination_device_id: uuid.UUID | str,
    test_id: uuid.UUID | str | None = None,
    actor: str = "system",
) -> PingTestCommand:
    """Lock the project, freeze its configuration and register the test command."""
    identifier = _as_uuid(project_id, "project_id")
    source = _as_uuid(source_device_id, "source_device_id")
    destination = _as_uuid(destination_device_id, "destination_device_id")
    test_uuid = uuid7() if test_id is None else _as_uuid(test_id, "test_id")

    project = _lock(session, identifier)
    for device_id, label in (
        (source, "source"),
        (destination, "destination"),
    ):
        device = session.scalars(
            select(Device).where(Device.project_id == identifier, Device.device_id == device_id)
        ).one_or_none()
        if device is None:
            raise ContractValidationError(
                f"{label} device {device_id} is not in project {identifier}"
            )
        if device.kind.value not in {"PC", "SERVER"}:
            raise ContractValidationError(
                f"{label} device must be a PC or SERVER (got {device.kind.value})"
            )

    snapshot = capture_snapshot(session, identifier, project=project)
    command = PingTestCommand(
        command_id=uuid7(),
        contract_version=CONTRACT_VERSION,
        test_id=test_uuid,
        project_id=identifier,
        source_device_id=source,
        destination_device_id=destination,
        test_kind="PING",
        expected_echo_requests=4,
        initial_runtime_state="FRESH",
        snapshot_id=snapshot.snapshot_id,
        created_at=utc_now(),
    )
    session.add(command)
    session.flush()
    _log_action(
        session,
        project,
        actor=actor,
        action_kind="PING_COMMAND_ACCEPTED",
        revision=project.state_revision,
        entity_type="ping_test_command",
        entity_id=test_uuid,
        detail={
            "snapshot_id": str(snapshot.snapshot_id),
            "configuration_digest": snapshot.configuration_digest,
            "base_state_revision": snapshot.base_state_revision,
            "base_simulation_revision": snapshot.base_simulation_revision,
        },
    )
    return command


def record_ping_result(
    session: Session,
    result: dict[str, Any],
    *,
    actor: str = "system",
) -> PingTestResult:
    """Store an immutable TASK-05 result and its exact canonical bytes."""
    _require_result_fields(result)
    _validate_task05_document(result, "PingTestResult")
    test_uuid = _as_uuid(result["test_id"], "test_id")
    command = session.scalars(
        select(PingTestCommand).where(PingTestCommand.test_id == test_uuid).with_for_update()
    ).one_or_none()
    if command is None:
        raise ContractValidationError(f"unknown Ping test_id {test_uuid}")
    if command.result is not None:
        raise PreconditionConflictError(f"Ping test {test_uuid} already has a recorded result")
    if command.contract_version != CONTRACT_VERSION:
        raise ContractValidationError(f"unsupported contract version {command.contract_version!r}")

    snapshot_ref = result["snapshot_ref"]
    if not isinstance(snapshot_ref, dict):
        raise ContractValidationError("snapshot_ref must be an object")
    snapshot_row = session.get(SnapshotRef, command.snapshot_id)
    if snapshot_row is None:
        raise ContractValidationError(
            f"snapshot {command.snapshot_id} referenced by the command does not exist"
        )
    expected = {
        "contract_version": CONTRACT_VERSION,
        "test_id": str(test_uuid),
        "project_id": str(command.project_id),
        "source_device_id": str(command.source_device_id),
        "destination_device_id": str(command.destination_device_id),
        "snapshot_id": str(command.snapshot_id),
        "base_state_revision": snapshot_row.base_state_revision,
        "base_simulation_revision": snapshot_row.base_simulation_revision,
    }
    for key, value in (
        ("contract_version", result.get("contract_version")),
        ("test_id", result.get("test_id")),
        ("project_id", result.get("project_id")),
        ("source_device_id", result.get("source_device_id")),
        ("destination_device_id", result.get("destination_device_id")),
        ("snapshot_id", snapshot_ref.get("snapshot_id")),
        ("base_state_revision", snapshot_ref.get("base_state_revision")),
        ("base_simulation_revision", snapshot_ref.get("base_simulation_revision")),
    ):
        if value is None:
            continue
        if key.endswith("_id") and isinstance(value, str):
            normalized = str(_as_uuid(value, key))
        elif key.endswith("_revision"):
            normalized = int(value)
        else:
            normalized = value
        if normalized != expected[key] and value is not None:
            raise ContractValidationError(
                f"result {key} {value!r} does not match accepted command {expected[key]!r}"
            )

    canonical = canonical_contract_bytes(result).decode("utf-8")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    project = session.get(Project, command.project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {command.project_id} does not exist")

    row = PingTestResult(
        test_id=test_uuid,
        contract_version=result.get("contract_version", CONTRACT_VERSION),
        project_id=command.project_id,
        source_device_id=command.source_device_id,
        destination_device_id=command.destination_device_id,
        snapshot_id=command.snapshot_id,
        lifecycle=result["lifecycle"],
        execution_status=ExecutionStatus(result["execution_status"]),
        aggregate_outcome=(
            None
            if result["aggregate_outcome"] is None
            else AggregateOutcome(result["aggregate_outcome"])
        ),
        observation_status=ObservationStatus(result["observation_status"]),
        started_at_ns=int(result["started_at_ns"]),
        finalized_at_ns=int(result["finalized_at_ns"]),
        closed_at_ns=int(result["closed_at_ns"]),
        statistics_json=result["statistics"],
        request_results_json=result["request_results"],
        diagnostics_json=result["diagnostics"],
        events_json=result["events"],
        hop_evidence_json=result["hop_evidence"],
        derived_warning_evidence_json=result["derived_warning_evidence"],
        canonical_json=canonical,
        result_sha256=digest,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()

    ping_log = PingLog(
        log_id=uuid7(),
        project_id=command.project_id,
        test_id=test_uuid,
        snapshot_id=command.snapshot_id,
        aggregate_outcome=row.aggregate_outcome,
        execution_status=row.execution_status,
        created_at=utc_now(),
    )
    session.add(ping_log)
    _log_action(
        session,
        project,
        actor=actor,
        action_kind="PING_RESULT_RECORDED",
        revision=project.state_revision,
        entity_type="ping_test_result",
        entity_id=test_uuid,
        detail={"result_sha256": digest},
    )
    return row


def get_ping_result(session: Session, test_id: uuid.UUID | str) -> PingTestResult:
    identifier = _as_uuid(test_id, "test_id")
    row = session.get(PingTestResult, identifier)
    if row is None:
        raise PreconditionConflictError(f"Ping result {identifier} does not exist")
    return row


# ---------------------------------------------------------------------------
# Structured errors
# ---------------------------------------------------------------------------


ERROR_ENVELOPE_REQUIRED = (
    "contract_version",
    "error_class",
    "code",
    "message_key",
    "details",
)


def record_error_envelope(
    session: Session,
    envelope: dict[str, Any],
    *,
    actor: str = "system",
) -> ErrorEnvelope:
    """Persist an immutable structured error plus its project-scoped log row."""
    missing = [field for field in ERROR_ENVELOPE_REQUIRED if field not in envelope]
    if missing:
        raise ContractValidationError(
            f"error envelope is missing required fields: {', '.join(missing)}"
        )
    error_uuid = uuid7()
    canonical_envelope = {
        **envelope,
        "error_id": str(error_uuid),
        "project_id": envelope.get("project_id"),
        "test_id": envelope.get("test_id"),
        "snapshot_ref": envelope.get("snapshot_ref"),
        "retryable": envelope.get("retryable", False),
    }
    _validate_task05_document(canonical_envelope, "ErrorEnvelope")
    error_class = canonical_envelope["error_class"]
    code = canonical_envelope["code"]
    canonical = canonical_contract_bytes(canonical_envelope).decode("utf-8")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    project_id = (
        None
        if canonical_envelope["project_id"] is None
        else _as_uuid(canonical_envelope["project_id"], "project_id")
    )
    test_id = (
        None
        if canonical_envelope["test_id"] is None
        else _as_uuid(canonical_envelope["test_id"], "test_id")
    )
    snapshot_ref = canonical_envelope["snapshot_ref"]
    snapshot_id = (
        None if snapshot_ref is None else _as_uuid(snapshot_ref["snapshot_id"], "snapshot_id")
    )

    row = ErrorEnvelope(
        error_id=error_uuid,
        contract_version=canonical_envelope["contract_version"],
        project_id=project_id,
        test_id=test_id,
        error_class=error_class,
        code=code,
        message_key=canonical_envelope["message_key"],
        details_json=canonical_envelope["details"],
        snapshot_id=snapshot_id,
        retryable=canonical_envelope["retryable"],
        canonical_json=canonical,
        canonical_sha256=digest,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()

    log = ErrorLog(
        log_id=uuid7(),
        project_id=project_id,
        error_id=row.error_id,
        error_class=error_class,
        code=code,
        message_key=canonical_envelope["message_key"],
        created_at=utc_now(),
    )
    session.add(log)
    session.flush()

    if project_id is not None:
        project = session.get(Project, project_id)
        if project is not None:
            _log_action(
                session,
                project,
                actor=actor,
                action_kind="ERROR_RECORDED",
                revision=project.state_revision,
                entity_type="error_envelope",
                entity_id=row.error_id,
                detail={"error_class": error_class, "code": code},
            )
    return row


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def load_retention_policy(session: Session, policy_name: str = DEFAULT_POLICY) -> RetentionPolicy:
    policy = session.get(RetentionPolicy, policy_name)
    if policy is None:
        raise PreconditionConflictError(f"retention policy {policy_name!r} is not configured")
    return policy


def purge_expired(session: Session, *, policy_name: str = DEFAULT_POLICY) -> dict[str, int]:
    """Delete expired evidence under the active retention policy.

    Only retention may remove immutable rows, so the whole operation runs with
    ``SET LOCAL syntra.purge_mode = 'on'``.  The returned counters are audit
    data; nothing else about the project state changes.
    """
    policy = load_retention_policy(session, policy_name)
    cutoff = utc_now()
    session.execute(text("SET LOCAL syntra.purge_mode = 'on'"))
    counts = {
        "action_log": 0,
        "ping_log": 0,
        "error_log": 0,
        "ping_result": 0,
        "snapshot_ref": 0,
        "error_envelope": 0,
    }

    counts["action_log"] = session.execute(
        sql_delete(ActionLog).where(
            ActionLog.created_at < cutoff - timedelta(days=policy.action_log_retention_days)
        )
    ).rowcount

    counts["ping_log"] = session.execute(
        sql_delete(PingLog).where(
            PingLog.created_at < cutoff - timedelta(days=policy.ping_log_retention_days)
        )
    ).rowcount

    counts["error_log"] = session.execute(
        sql_delete(ErrorLog).where(
            ErrorLog.created_at < cutoff - timedelta(days=policy.error_log_retention_days)
        )
    ).rowcount
    counts["error_envelope"] = session.execute(
        sql_delete(ErrorEnvelope).where(
            ErrorEnvelope.created_at < cutoff - timedelta(days=policy.error_log_retention_days)
        )
    ).rowcount

    counts["ping_result"] = session.execute(
        sql_delete(PingTestResult).where(
            PingTestResult.created_at < cutoff - timedelta(days=policy.ping_result_retention_days)
        )
    ).rowcount

    counts["snapshot_ref"] = session.execute(
        sql_delete(SnapshotRef).where(
            SnapshotRef.created_at < cutoff - timedelta(days=policy.snapshot_retention_days)
        )
    ).rowcount
    return counts


__all__ = [
    "accept_ping_command",
    "record_ping_result",
    "get_ping_result",
    "record_error_envelope",
    "load_retention_policy",
    "purge_expired",
    "canonical_contract_bytes",
]
