"""Phase 2: result assembler output is schema-valid and semantically self-consistent.

Every assembled document is checked against the frozen TASK-05 JSON Schema and
``verify_contract.check()`` (loaded read-only from the reference bundle). The
frozen examples are used only as oracles for shape/correlation decisions; no
example is copied or returned as a produced result.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app.engine.ping import (
    DiagnosticEvidence,
    EventEvidence,
    HopEvidence,
    RequestEvidence,
    ResultAssemblyError,
    ResultEvidence,
    assemble_result,
)

ROOT = Path(__file__).resolve().parents[3]
TASK05 = ROOT / "contracts" / "reference" / "task05"

TEST_ID = "019a5000-0000-7000-8000-000000000014"
PROJECT_ID = "019a5000-0000-7000-8000-000000000001"
SOURCE_ID = "019a5000-0000-7000-8000-000000000002"
DESTINATION_ID = "019a5000-0000-7000-8000-000000000003"
SNAPSHOT_ID = "019a5000-0000-7000-8000-000000000004"
EGRESS_ID = "019a5000-0000-7000-8000-000000000006"
INGRESS_ID = "019a5000-0000-7000-8000-000000000007"
CONNECTION_ID = "019a5000-0000-7000-8000-000000000005"

SNAPSHOT_REF = {
    "project_id": PROJECT_ID,
    "snapshot_id": SNAPSHOT_ID,
    "base_state_revision": 12,
    "base_simulation_revision": 10,
    "schema_version": "1.0.0",
    "configuration_digest": "a" * 64,
}

_SCHEMA = json.loads((TASK05 / "schemas" / "task05-contract-v1.schema.json").read_text())
Draft202012Validator.check_schema(_SCHEMA)
SCHEMA_VALIDATOR = Draft202012Validator(_SCHEMA)


def _verifier():
    path = TASK05 / "tools" / "verify_contract.py"
    spec = importlib.util.spec_from_file_location("task05_verify_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _verifier()


def _assert_valid(document: dict[str, Any]) -> None:
    schema_errors = list(SCHEMA_VALIDATOR.iter_errors(document))
    assert not schema_errors, f"SCHEMA: {[e.message for e in schema_errors[:3]]}"
    assert VERIFIER.check(document) == []


def _match_event(
    sequence: int, finalized_at_ns: int, packet_id: str, *, index: int
) -> EventEvidence:
    return EventEvidence(
        event_id=f"ev-match-{sequence}",
        virtual_time_ns=finalized_at_ns,
        phase=40,
        kind="ICMP_ECHO_MATCHED",
        direction="RETURN",
        execution_index=index,
        creation_sequence=index,
        request_sequence=sequence,
        device_id=DESTINATION_ID,
        packet_id=packet_id,
    )


def _success_evidence(*, include_frame_hops: bool = True) -> ResultEvidence:
    requests: list[RequestEvidence] = []
    match_data: list[tuple[int, int]] = []
    for sequence in range(1, 5):
        started = (sequence - 1) * 1_000_000_000
        emitted = started + 100_000
        finalized = started + 350_000
        requests.append(
            RequestEvidence(
                outcome="SUCCESS",
                started_at_ns=started,
                finalized_at_ns=finalized,
                emitted_at_ns=emitted,
                matched_reply_event_id=f"ev-match-{sequence}",
                forward_path_status="COMPLETED",
                return_path_status="COMPLETED",
            )
        )
        match_data.append((sequence, finalized))

    events: list[EventEvidence] = []
    hops: list[HopEvidence] = []
    if include_frame_hops:
        # A witnessed L2 hop for request 1: emitted frame TX at 120000 and the
        # matching ARRIVAL at 220000, both referenced by the hop evidence.
        events.extend(
            [
                EventEvidence(
                    event_id="ev-tx-1",
                    virtual_time_ns=120_000,
                    phase=40,
                    kind="FRAME_TX",
                    direction="FORWARD",
                    execution_index=1,
                    creation_sequence=1,
                    request_sequence=1,
                    device_id=SOURCE_ID,
                    egress_interface_id=EGRESS_ID,
                    packet_id="pkt-1",
                    frame_id="frame-1",
                    connection_id=CONNECTION_ID,
                ),
                EventEvidence(
                    event_id="ev-rx-1",
                    virtual_time_ns=220_000,
                    phase=40,
                    kind="FRAME_ARRIVED",
                    direction="FORWARD",
                    execution_index=2,
                    creation_sequence=2,
                    request_sequence=1,
                    device_id=DESTINATION_ID,
                    ingress_interface_id=INGRESS_ID,
                    packet_id="pkt-1",
                    frame_id="frame-1",
                    connection_id=CONNECTION_ID,
                ),
            ]
        )
        hops.append(
            HopEvidence(
                hop_id="hop-1",
                packet_id="pkt-1",
                frame_id="frame-1",
                request_sequence=1,
                direction="FORWARD",
                from_device_id=SOURCE_ID,
                to_device_id=DESTINATION_ID,
                egress_interface_id=EGRESS_ID,
                ingress_interface_id=INGRESS_ID,
                connection_id=CONNECTION_ID,
                tx_start_ns=120_000,
                rx_complete_ns=220_000,
                outcome="DELIVERED",
                source_event_ids=("ev-tx-1", "ev-rx-1"),
            )
        )

    offset = len(events)
    for sequence, finalized in match_data:
        events.append(_match_event(sequence, finalized, f"pkt-{sequence}", index=offset + sequence))

    return ResultEvidence(
        test_id=TEST_ID,
        project_id=PROJECT_ID,
        source_device_id=SOURCE_ID,
        destination_device_id=DESTINATION_ID,
        snapshot_ref=SNAPSHOT_REF,
        requests=tuple(requests),
        events=tuple(events),
        hops=tuple(hops),
    )


def _failure_evidence(
    *, sent: bool = True, code: str = "ARP_NO_RESPONSE", direction: str = "FORWARD"
) -> ResultEvidence:
    requests: list[RequestEvidence] = []
    diagnostics: list[DiagnosticEvidence] = []
    for sequence in range(1, 5):
        started = (sequence - 1) * 1_000_000_000
        finalized = started + 1_000_000_000
        requests.append(
            RequestEvidence(
                outcome="FAILED",
                started_at_ns=started,
                finalized_at_ns=finalized,
                emitted_at_ns=started + 100_000 if sent else None,
                primary_diagnostic_id=f"d-{sequence}",
                forward_path_status="COMPLETED" if direction == "RETURN" else "UNKNOWN",
                return_path_status="FAILED" if direction == "RETURN" else "UNKNOWN",
            )
        )
        diagnostics.append(
            DiagnosticEvidence(
                diagnostic_id=f"d-{sequence}",
                code=code,
                classification="SIMULATION_FAILURE",
                is_primary=True,
                request_sequence=sequence,
                direction=direction,
                detected_at_ns=finalized,
                detected_device_id=SOURCE_ID,
                evidence_completeness="COMPLETE",
            )
        )
    return ResultEvidence(
        test_id=TEST_ID,
        project_id=PROJECT_ID,
        source_device_id=SOURCE_ID,
        destination_device_id=DESTINATION_ID,
        snapshot_ref=SNAPSHOT_REF,
        requests=tuple(requests),
        diagnostics=tuple(diagnostics),
    )


# --- full-document verification ----------------------------------------------


def test_all_success_document_validates_against_schema_and_semantics():
    document = assemble_result(_success_evidence())
    _assert_valid(document)

    assert document["execution_status"] == "COMPLETED"
    assert document["aggregate_outcome"] == "SUCCESS"
    assert document["observation_status"] == "COMPLETE"
    assert document["lifecycle"] == "CLOSED"
    assert document["statistics"] == {
        "requests_planned": 4,
        "requests_started": 4,
        "requests_sent": 4,
        "replies_received": 4,
        "lost_sent_requests": 0,
        "loss_percentage_hundredths": 0,
        "rtt_min_ns": 250_000,
        "rtt_max_ns": 250_000,
        "rtt_sum_ns": 1_000_000,
        "rtt_avg_ns_rounded": 250_000,
    }
    assert len(document["hop_evidence"]) == 1
    assert document["hop_evidence"][0]["source_event_ids"] == ["ev-tx-1", "ev-rx-1"]


def test_partial_success_and_failure_documents_validate():
    evidence = _success_evidence(include_frame_hops=False)
    requests = list(evidence.requests)
    events = list(evidence.events)
    # Two replies matched, two timed out at their deadlines.
    for index in (2, 3):
        started = requests[index].started_at_ns
        requests[index] = RequestEvidence(
            outcome="TIMEOUT",
            started_at_ns=started,
            finalized_at_ns=started + 1_000_000_000,
            emitted_at_ns=started + 100_000,
        )
    events = events[:2]
    partial = assemble_result(replace(evidence, requests=tuple(requests), events=tuple(events)))
    _assert_valid(partial)
    assert partial["aggregate_outcome"] == "PARTIAL_SUCCESS"
    assert partial["statistics"]["replies_received"] == 2
    assert partial["statistics"]["loss_percentage_hundredths"] == 5000
    assert partial["statistics"]["rtt_avg_ns_rounded"] == 250_000

    failure = assemble_result(_failure_evidence())
    _assert_valid(failure)
    assert failure["aggregate_outcome"] == "FAILURE"
    assert failure["statistics"]["loss_percentage_hundredths"] == 10000
    assert failure["statistics"]["rtt_min_ns"] is None
    assert failure["statistics"]["rtt_avg_ns_rounded"] is None


def test_zero_sent_document_validates_with_null_loss():
    document = assemble_result(_failure_evidence(sent=False))
    _assert_valid(document)
    assert document["statistics"]["requests_sent"] == 0
    assert document["statistics"]["lost_sent_requests"] == 0
    assert document["statistics"]["loss_percentage_hundredths"] is None


def test_return_route_failure_document_validates():
    document = assemble_result(_failure_evidence(code="NO_MATCHING_ROUTE", direction="RETURN"))
    _assert_valid(document)
    assert document["request_results"][0]["forward_path_status"] == "COMPLETED"
    assert document["request_results"][0]["return_path_status"] == "FAILED"


def test_incomplete_document_validates():
    first = RequestEvidence(
        outcome="SUCCESS",
        started_at_ns=0,
        finalized_at_ns=350_000,
        emitted_at_ns=100_000,
        matched_reply_event_id="ev-match-1",
        forward_path_status="COMPLETED",
        return_path_status="COMPLETED",
    )
    second = RequestEvidence(
        outcome="EXECUTION_LIMITED",
        started_at_ns=1_000_000_000,
        finalized_at_ns=1_500_000_000,
        emitted_at_ns=1_000_100_000,
        primary_diagnostic_id="d-limit",
    )
    limit = DiagnosticEvidence(
        diagnostic_id="d-limit",
        code="REQUEST_EVENT_BUDGET_EXHAUSTED",
        classification="EXECUTION_LIMIT",
        is_primary=True,
        request_sequence=2,
        direction="NONE",
        detected_at_ns=1_500_000_000,
    )
    evidence = ResultEvidence(
        test_id=TEST_ID,
        project_id=PROJECT_ID,
        source_device_id=SOURCE_ID,
        destination_device_id=DESTINATION_ID,
        snapshot_ref=SNAPSHOT_REF,
        execution_status="INCOMPLETE",
        observation_status="NOT_STARTED",
        requests=(first, second),
        events=(_match_event(1, 350_000, "pkt-1", index=1),),
        diagnostics=(limit,),
    )
    document = assemble_result(evidence)
    _assert_valid(document)
    assert document["aggregate_outcome"] is None
    assert document["observation_status"] == "NOT_STARTED"
    assert document["statistics"]["requests_started"] == 2


def test_self_ping_has_no_hops_and_validates():
    evidence = _success_evidence(include_frame_hops=False)
    document = assemble_result(replace(evidence, destination_device_id=SOURCE_ID))
    _assert_valid(document)
    assert document["hop_evidence"] == []


def test_rounding_is_half_up_to_contract_precision():
    # 3 replies out of 4 sent -> 25.00% (2500 hundredths), RTT avg of
    # 250000 + 250001 + 250002 = 750003 / 3 = 250001 (half-up).
    requests = []
    events = []
    for sequence, (outcome, rtt) in enumerate(
        [("SUCCESS", 250_000), ("SUCCESS", 250_001), ("SUCCESS", 250_002), ("FAILED", None)],
        start=1,
    ):
        started = (sequence - 1) * 1_000_000_000
        emitted = started + 100_000
        finalized = started + 100_000 + rtt if rtt is not None else started + 1_000_000_000
        if rtt is not None:
            events.append(_match_event(sequence, finalized, f"pkt-{sequence}", index=sequence))
            requests.append(
                RequestEvidence(
                    outcome=outcome,
                    started_at_ns=started,
                    finalized_at_ns=finalized,
                    emitted_at_ns=emitted,
                    matched_reply_event_id=f"ev-match-{sequence}",
                    forward_path_status="COMPLETED",
                    return_path_status="COMPLETED",
                )
            )
        else:
            requests.append(
                RequestEvidence(
                    outcome=outcome,
                    started_at_ns=started,
                    finalized_at_ns=finalized,
                    emitted_at_ns=emitted,
                )
            )
    document = assemble_result(
        replace(
            _success_evidence(include_frame_hops=False),
            requests=tuple(requests),
            events=tuple(events),
        )
    )
    _assert_valid(document)
    assert document["statistics"]["loss_percentage_hundredths"] == 2500
    assert document["statistics"]["rtt_avg_ns_rounded"] == 250_001


# --- fail-closed validation ---------------------------------------------------


def _bad_evidence_cases() -> list[tuple[str, ResultEvidence]]:
    base = _success_evidence(include_frame_hops=False)
    cases: list[tuple[str, ResultEvidence]] = []

    def with_field(**changes: Any) -> ResultEvidence:
        return replace(base, **changes)

    request_list = list(base.requests)
    request_list[3] = RequestEvidence(
        outcome="SUCCESS",
        started_at_ns=3_000_000_000,
        finalized_at_ns=3_000_400_000,
        emitted_at_ns=3_000_100_000,
        matched_reply_event_id="missing-match",
        forward_path_status="COMPLETED",
        return_path_status="COMPLETED",
    )
    cases.append(("missing-match", with_field(requests=tuple(request_list))))

    events = list(base.events)
    events[0] = replace(events[0], execution_index=99)
    cases.append(("execution-order", with_field(events=tuple(events))))

    bad_diag = DiagnosticEvidence(
        diagnostic_id="d-extra",
        code="MAC_FLAPPING_DETECTED",
        classification="WARNING",
        is_primary=True,
        request_sequence=1,
        direction="NONE",
        trigger_event_id="ev-unknown",
    )
    cases.append(("diag-trigger", with_field(diagnostics=(bad_diag,))))

    wrong_snapshot = dict(SNAPSHOT_REF)
    wrong_snapshot["project_id"] = "019a5000-0000-7000-8000-000000000009"
    cases.append(("snapshot-project", with_field(snapshot_ref=wrong_snapshot)))

    hop = HopEvidence(
        hop_id="hop-x",
        packet_id="pkt-1",
        frame_id="frame-1",
        request_sequence=1,
        direction="FORWARD",
        from_device_id=SOURCE_ID,
        to_device_id=DESTINATION_ID,
        egress_interface_id=EGRESS_ID,
        ingress_interface_id=INGRESS_ID,
        connection_id=CONNECTION_ID,
        tx_start_ns=120_000,
        rx_complete_ns=None,
        outcome="DELIVERED",
    )
    cases.append(("delivered-time", with_field(hops=(hop,))))

    return cases


@pytest.mark.parametrize("label,evidence", _bad_evidence_cases())
def test_inconsistent_evidence_is_rejected(label, evidence):
    with pytest.raises(ResultAssemblyError):
        assemble_result(evidence)


def test_self_ping_with_hops_is_rejected():
    evidence = _success_evidence(include_frame_hops=True)
    with pytest.raises(ResultAssemblyError, match="self-ping-no-hops"):
        assemble_result(replace(evidence, destination_device_id=SOURCE_ID))


def test_completed_with_execution_limited_is_rejected():
    base = _success_evidence(include_frame_hops=False)
    requests = list(base.requests)
    requests[0] = RequestEvidence(
        outcome="EXECUTION_LIMITED",
        started_at_ns=0,
        finalized_at_ns=1_000_000,
    )
    with pytest.raises(ResultAssemblyError, match="EXECUTION_LIMITED"):
        assemble_result(replace(base, requests=tuple(requests)))


def test_no_synthesized_presentation_metadata_leaks_into_result():
    document = assemble_result(_success_evidence())
    serialized = json.dumps(document)
    for forbidden in ("display_name", "position", "created_at", "updated_at", "rotation"):
        assert forbidden not in serialized


def test_assembled_document_is_deterministic():
    first = assemble_result(_success_evidence())
    second = assemble_result(_success_evidence())
    assert first == second
