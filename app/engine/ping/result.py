"""Phase 2: assemble raw simulation observations into a TASK-05 result document.

This module is the *only* place that turns simulation evidence into the wire
contract. It derives every field whose value is fixed by the contract
(statistics, rounding, aggregate outcome, deadlines, RTTs) and it fail-closes
on any internally inconsistent evidence before a document is returned.

The assembler never invents network outcomes: ``ResultEvidence`` is supplied by
the event-driven core (phase 3). Unit tests feed it constructed observations as
oracles, exactly as the frozen TASK-05 examples are used as oracles — no code
path here can produce a result for a configuration that was not simulated.

No database, API, clock or topology mutation is involved. Synthesised
presentation metadata from the replay adapter never reaches this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.engine.clock.queue import PING_DEADLINE_NS
from app.engine.topology.models import is_uuid7

CONTRACT_VERSION = "1.0.0"
REQUESTS_PLANNED = 4
DEFAULT_ICMP_IDENTIFIER = 1234

_OUTCOMES = frozenset({"SUCCESS", "FAILED", "TIMEOUT", "EXECUTION_LIMITED"})
_EXECUTION_STATUSES = frozenset({"COMPLETED", "INCOMPLETE"})
_OBSERVATION_STATUSES = frozenset({"COMPLETE", "TRUNCATED", "NOT_STARTED"})
_PATH_STATUSES = frozenset({"COMPLETED", "FAILED", "NOT_STARTED", "UNKNOWN"})


class ResultAssemblyError(ValueError):
    """Raised when simulation evidence cannot form a valid TASK-05 result."""


@dataclass(frozen=True, slots=True)
class EventEvidence:
    """One evidence event produced by the deterministic event queue."""

    event_id: str
    virtual_time_ns: int
    phase: int
    kind: str
    direction: str
    execution_index: int
    creation_sequence: int
    request_sequence: int | None = None
    device_id: str | None = None
    ingress_interface_id: str | None = None
    egress_interface_id: str | None = None
    connection_id: str | None = None
    packet_id: str | None = None
    frame_id: str | None = None
    parent_frame_id: str | None = None
    lineage_id: str | None = None
    resolution_id: str | None = None
    diagnostic_id: str | None = None
    facts: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    """One TASK-05 diagnostic observed by the simulation."""

    diagnostic_id: str
    code: str
    classification: str
    is_primary: bool
    request_sequence: int | None
    direction: str
    detected_at_ns: int | None = None
    detected_device_id: str | None = None
    detected_interface_id: str | None = None
    trigger_event_id: str | None = None
    evidence_completeness: str = "COMPLETE"
    facts: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HopEvidence:
    """One physical L2 hop witnessed by a frame TX/ARRIVAL event pair."""

    hop_id: str
    packet_id: str
    frame_id: str
    request_sequence: int
    direction: str
    from_device_id: str
    to_device_id: str
    egress_interface_id: str
    ingress_interface_id: str
    connection_id: str
    tx_start_ns: int
    rx_complete_ns: int | None
    outcome: str
    drop_diagnostic_id: str | None = None
    source_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RequestEvidence:
    """The simulated outcome of one echo request (sequence assigned here)."""

    outcome: str
    started_at_ns: int
    finalized_at_ns: int
    emitted_at_ns: int | None = None
    matched_reply_event_id: str | None = None
    primary_diagnostic_id: str | None = None
    forward_path_status: str = "UNKNOWN"
    return_path_status: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResultEvidence:
    """Complete raw observation set handed to the assembler by the runner."""

    test_id: UUID | str
    project_id: UUID | str
    source_device_id: UUID | str
    destination_device_id: UUID | str
    snapshot_ref: Mapping[str, object]
    execution_status: str = "COMPLETED"
    observation_status: str = "COMPLETE"
    started_at_ns: int = 0
    finalized_at_ns: int | None = None
    closed_at_ns: int | None = None
    icmp_identifier: int = DEFAULT_ICMP_IDENTIFIER
    requests: tuple[RequestEvidence, ...] = ()
    events: tuple[EventEvidence, ...] = ()
    diagnostics: tuple[DiagnosticEvidence, ...] = ()
    hops: tuple[HopEvidence, ...] = ()
    warnings: tuple[Mapping[str, object], ...] = ()


def _as_wire_uuid(value: UUID | str, name: str) -> str:
    text = str(value)
    if not is_uuid7(text):
        raise ResultAssemblyError(f"{name} must be a lowercase UUIDv7")
    return text


def _require_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResultAssemblyError(f"{name} must be a non-negative integer")
    return value


def _build_request_rows(evidence: ResultEvidence) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sequence, request in enumerate(evidence.requests, start=1):
        started = _require_nonnegative_int(request.started_at_ns, "request started_at_ns")
        finalized = _require_nonnegative_int(request.finalized_at_ns, "request finalized_at_ns")
        emitted = (
            None
            if request.emitted_at_ns is None
            else _require_nonnegative_int(request.emitted_at_ns, "request emitted_at_ns")
        )
        rtt = None
        if request.outcome == "SUCCESS" and emitted is not None:
            rtt = finalized - emitted
        rows.append(
            {
                "sequence": sequence,
                "icmp_identifier": evidence.icmp_identifier,
                "outcome": request.outcome,
                "started_at_ns": started,
                "deadline_at_ns": started + PING_DEADLINE_NS,
                "echo_request_emitted_at_ns": emitted,
                "finalized_at_ns": finalized,
                "matched_reply_event_id": request.matched_reply_event_id,
                "rtt_ns": rtt,
                "primary_diagnostic_id": request.primary_diagnostic_id,
                "forward_path_status": request.forward_path_status,
                "return_path_status": request.return_path_status,
            }
        )
    return rows


def _build_statistics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    replies = sum(row["outcome"] == "SUCCESS" for row in rows)
    sent = sum(row["echo_request_emitted_at_ns"] is not None for row in rows)
    loss = None if sent == 0 else (2 * 10000 * (sent - replies) // sent + 1) // 2
    rtts = [row["rtt_ns"] for row in rows if row["outcome"] == "SUCCESS"]
    return {
        "requests_planned": REQUESTS_PLANNED,
        "requests_started": len(rows),
        "requests_sent": sent,
        "replies_received": replies,
        "lost_sent_requests": sent - replies,
        "loss_percentage_hundredths": loss,
        "rtt_min_ns": min(rtts) if rtts else None,
        "rtt_max_ns": max(rtts) if rtts else None,
        "rtt_sum_ns": sum(rtts) if rtts else None,
        "rtt_avg_ns_rounded": (2 * sum(rtts) // len(rtts) + 1) // 2 if rtts else None,
    }


def _build_event_rows(evidence: ResultEvidence) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "creation_sequence": event.creation_sequence,
            "execution_index": event.execution_index,
            "virtual_time_ns": event.virtual_time_ns,
            "phase": event.phase,
            "kind": event.kind,
            "direction": event.direction,
            "request_sequence": event.request_sequence,
            "device_id": event.device_id,
            "ingress_interface_id": event.ingress_interface_id,
            "egress_interface_id": event.egress_interface_id,
            "connection_id": event.connection_id,
            "packet_id": event.packet_id,
            "frame_id": event.frame_id,
            "parent_frame_id": event.parent_frame_id,
            "lineage_id": event.lineage_id,
            "resolution_id": event.resolution_id,
            "diagnostic_id": event.diagnostic_id,
            "facts": dict(event.facts),
        }
        for event in evidence.events
    ]


def _build_diagnostic_rows(evidence: ResultEvidence) -> list[dict[str, Any]]:
    return [
        {
            "diagnostic_id": diagnostic.diagnostic_id,
            "code": diagnostic.code,
            "classification": diagnostic.classification,
            "is_primary": diagnostic.is_primary,
            "request_sequence": diagnostic.request_sequence,
            "direction": diagnostic.direction,
            "detected_at_ns": diagnostic.detected_at_ns,
            "detected_device_id": diagnostic.detected_device_id,
            "detected_interface_id": diagnostic.detected_interface_id,
            "trigger_event_id": diagnostic.trigger_event_id,
            "evidence_completeness": diagnostic.evidence_completeness,
            "facts": dict(diagnostic.facts),
        }
        for diagnostic in evidence.diagnostics
    ]


def _build_hop_rows(evidence: ResultEvidence) -> list[dict[str, Any]]:
    return [
        {
            "hop_id": hop.hop_id,
            "packet_id": hop.packet_id,
            "frame_id": hop.frame_id,
            "request_sequence": hop.request_sequence,
            "direction": hop.direction,
            "from_device_id": hop.from_device_id,
            "to_device_id": hop.to_device_id,
            "egress_interface_id": hop.egress_interface_id,
            "ingress_interface_id": hop.ingress_interface_id,
            "connection_id": hop.connection_id,
            "tx_start_ns": hop.tx_start_ns,
            "rx_complete_ns": hop.rx_complete_ns,
            "outcome": hop.outcome,
            "drop_diagnostic_id": hop.drop_diagnostic_id,
            "source_event_ids": list(hop.source_event_ids),
        }
        for hop in evidence.hops
    ]


def _validate(
    evidence: ResultEvidence,
    *,
    project_id: str,
    requests: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
    hops: Sequence[Mapping[str, Any]],
    started_at_ns: int,
    finalized_at_ns: int,
    closed_at_ns: int,
    aggregate_outcome: str | None,
) -> None:
    def need(condition: bool, label: str) -> None:
        if not condition:
            raise ResultAssemblyError(f"inconsistent evidence: {label}")

    snapshot = evidence.snapshot_ref
    need(isinstance(snapshot, Mapping), "snapshot_ref must be a mapping")
    need(snapshot.get("project_id") == project_id, "snapshot-project")
    need(is_uuid7(str(snapshot.get("snapshot_id", ""))), "snapshot_id must be a UUIDv7")
    need(
        _require_nonnegative_int(snapshot.get("base_simulation_revision", -1), "sim revision")
        <= _require_nonnegative_int(snapshot.get("base_state_revision", -1), "state revision"),
        "snapshot-revisions",
    )

    need(started_at_ns <= finalized_at_ns <= closed_at_ns, "test-time-order")
    need(
        evidence.execution_status in _EXECUTION_STATUSES,
        "execution_status must be COMPLETED or INCOMPLETE",
    )
    need(evidence.observation_status in _OBSERVATION_STATUSES, "observation_status is invalid")
    need(0 <= evidence.icmp_identifier <= 0xFFFF, "icmp_identifier must be a 16-bit integer")
    need(len(requests) <= REQUESTS_PLANNED, "at most four requests")

    if evidence.execution_status == "INCOMPLETE":
        need(aggregate_outcome is None, "INCOMPLETE must not have an aggregate outcome")
        need(evidence.observation_status == "NOT_STARTED", "INCOMPLETE must not be observed")
    else:
        need(len(requests) == REQUESTS_PLANNED, "COMPLETED requires four requests")
        need(
            all(row["outcome"] != "EXECUTION_LIMITED" for row in requests),
            "COMPLETED cannot include EXECUTION_LIMITED",
        )
        need(aggregate_outcome is not None, "COMPLETED requires an aggregate outcome")

    need(len({row["icmp_identifier"] for row in requests}) <= 1, "multiple ICMP identifiers")
    need(
        all(row["outcome"] in _OUTCOMES for row in requests),
        "request outcome is not in the TASK-05 vocabulary",
    )
    need(
        all(row["forward_path_status"] in _PATH_STATUSES for row in requests),
        "forward_path_status is invalid",
    )
    need(
        all(row["return_path_status"] in _PATH_STATUSES for row in requests),
        "return_path_status is invalid",
    )

    event_ids = [event["event_id"] for event in events]
    diagnostic_ids = [diagnostic["diagnostic_id"] for diagnostic in diagnostics]
    hop_ids = [hop["hop_id"] for hop in hops]
    need(len(event_ids) == len(set(event_ids)), "duplicate-event-id")
    need(len(diagnostic_ids) == len(set(diagnostic_ids)), "duplicate-diagnostic-id")
    need(len(hop_ids) == len(set(hop_ids)), "duplicate-hop-id")
    need(len({e["execution_index"] for e in events}) == len(events), "duplicate-exec-index")
    need(len({e["creation_sequence"] for e in events}) == len(events), "duplicate-create-seq")
    need(len(events) <= 40000, "event-budget")
    need(
        all(
            events[i]["execution_index"] < events[i + 1]["execution_index"]
            and events[i]["virtual_time_ns"] <= events[i + 1]["virtual_time_ns"]
            for i in range(len(events) - 1)
        ),
        "event-execution-order",
    )

    event_by_id = {event["event_id"]: event for event in events}
    diagnostic_by_id = {diagnostic["diagnostic_id"]: diagnostic for diagnostic in diagnostics}

    primary_by_sequence: dict[int, int] = {}
    for diagnostic in diagnostics:
        trigger = diagnostic["trigger_event_id"]
        need(trigger is None or trigger in event_by_id, "diag-trigger-reference")
        if diagnostic["is_primary"]:
            sequence = diagnostic["request_sequence"]
            need(sequence is not None, "primary-request-correlation")
            primary_by_sequence[sequence] = primary_by_sequence.get(sequence, 0) + 1
    need(all(count <= 1 for count in primary_by_sequence.values()), "multiple-primary")

    matched_reply_ids: list[str] = []
    for index, row in enumerate(requests):
        sequence = row["sequence"]
        need(row["deadline_at_ns"] == row["started_at_ns"] + PING_DEADLINE_NS, "deadline")
        need(
            row["started_at_ns"] <= row["finalized_at_ns"] <= row["deadline_at_ns"],
            "request-time",
        )
        if index:
            need(
                requests[index - 1]["finalized_at_ns"] <= row["started_at_ns"], "attempt-nonoverlap"
            )
        emitted = row["echo_request_emitted_at_ns"]
        need(
            emitted is None or row["started_at_ns"] <= emitted <= row["finalized_at_ns"],
            "emission-time",
        )
        if row["outcome"] == "SUCCESS":
            match_id = row["matched_reply_event_id"]
            need(match_id in event_by_id, "match-reference")
            if match_id is not None:
                match = event_by_id[match_id]
                need(
                    match["kind"] == "ICMP_ECHO_MATCHED" and match["request_sequence"] == sequence,
                    "match-event-kind-seq",
                )
                need(match["virtual_time_ns"] == row["finalized_at_ns"], "match-time")
            need(
                emitted is not None and row["rtt_ns"] == row["finalized_at_ns"] - emitted,
                "rtt-derivation",
            )
            need(row["primary_diagnostic_id"] is None, "success-no-primary")
            if match_id is not None:
                matched_reply_ids.append(match_id)
        else:
            need(
                row["matched_reply_event_id"] is None and row["rtt_ns"] is None,
                "nonsuccess-no-match",
            )
        primary_id = row["primary_diagnostic_id"]
        if primary_id is not None:
            match = diagnostic_by_id.get(primary_id)
            need(
                match is not None and match["is_primary"] and match["request_sequence"] == sequence,
                "primary-reference",
            )
    need(len(matched_reply_ids) == len(set(matched_reply_ids)), "duplicate-matched-reply")

    for hop in hops:
        need(
            all(source in event_by_id for source in hop["source_event_ids"]), "hop-event-reference"
        )
        drop_id = hop["drop_diagnostic_id"]
        need(drop_id is None or drop_id in diagnostic_by_id, "hop-diag-reference")
        need(
            hop["outcome"] != "DELIVERED"
            or (hop["rx_complete_ns"] is not None and hop["rx_complete_ns"] >= hop["tx_start_ns"]),
            "delivered-time",
        )
        need(hop["outcome"] != "DROPPED" or drop_id is not None, "drop-cause")
        need(hop["direction"] != "LOCAL", "physical-hop-local")
    if str(evidence.source_device_id) == str(evidence.destination_device_id):
        need(not hops, "self-ping-no-hops")


def assemble_result(evidence: ResultEvidence) -> dict[str, object]:
    """Build one complete, internally consistent TASK-05 result document.

    Raises ``ResultAssemblyError`` if the supplied evidence violates any
    semantic rule of the frozen contract; no partial document is returned.
    """
    if not isinstance(evidence.snapshot_ref, Mapping):
        raise ResultAssemblyError("snapshot_ref must be a mapping")
    test_id = _as_wire_uuid(evidence.test_id, "test_id")
    project_id = _as_wire_uuid(evidence.project_id, "project_id")
    source_id = _as_wire_uuid(evidence.source_device_id, "source_device_id")
    destination_id = _as_wire_uuid(evidence.destination_device_id, "destination_device_id")

    if evidence.snapshot_ref.get("project_id") != project_id:
        raise ResultAssemblyError("snapshot_ref.project_id must equal project_id")

    requests = _build_request_rows(evidence)
    events = _build_event_rows(evidence)
    diagnostics = _build_diagnostic_rows(evidence)
    hops = _build_hop_rows(evidence)
    statistics = _build_statistics(requests)

    replies = statistics["replies_received"]
    if evidence.execution_status == "COMPLETED":
        aggregate_outcome: str | None = (
            "SUCCESS"
            if replies == REQUESTS_PLANNED
            else "PARTIAL_SUCCESS"
            if replies
            else "FAILURE"
        )
    else:
        aggregate_outcome = None

    started = _require_nonnegative_int(evidence.started_at_ns, "started_at_ns")
    finalized = (
        started
        if evidence.finalized_at_ns is None
        else _require_nonnegative_int(evidence.finalized_at_ns, "finalized_at_ns")
    )
    if requests:
        finalized = max(finalized, max(row["finalized_at_ns"] for row in requests))
    closed = (
        finalized
        if evidence.closed_at_ns is None
        else _require_nonnegative_int(evidence.closed_at_ns, "closed_at_ns")
    )

    _validate(
        evidence,
        project_id=project_id,
        requests=requests,
        events=events,
        diagnostics=diagnostics,
        hops=hops,
        started_at_ns=started,
        finalized_at_ns=finalized,
        closed_at_ns=closed,
        aggregate_outcome=aggregate_outcome,
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "test_id": test_id,
        "project_id": project_id,
        "source_device_id": source_id,
        "destination_device_id": destination_id,
        "snapshot_ref": dict(evidence.snapshot_ref),
        "lifecycle": "CLOSED",
        "execution_status": evidence.execution_status,
        "aggregate_outcome": aggregate_outcome,
        "observation_status": evidence.observation_status,
        "started_at_ns": started,
        "finalized_at_ns": finalized,
        "closed_at_ns": closed,
        "statistics": statistics,
        "request_results": requests,
        "diagnostics": diagnostics,
        "events": events,
        "hop_evidence": hops,
        "derived_warning_evidence": [dict(warning) for warning in evidence.warnings],
    }


__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_ICMP_IDENTIFIER",
    "DiagnosticEvidence",
    "EventEvidence",
    "HopEvidence",
    "RequestEvidence",
    "ResultAssemblyError",
    "ResultEvidence",
    "assemble_result",
]
