import re

import pytest

from app.engine.diagnostics.codes import (
    DiagnosticClassification,
    DiagnosticCode,
    Direction,
    EvidenceCompleteness,
)

# Pinned copy of the TASK-05 v1.0.0 dictionary. Changing the enum without changing this list
# (and getting contract approval) must fail the test.
EXPECTED_CODES = {
    # Source / endpoint
    "SOURCE_IPV4_UNCONFIGURED",
    "SOURCE_INTERFACE_DISABLED",
    "SOURCE_LINK_DOWN",
    "UNSUPPORTED_PING_ENDPOINT",
    "DUPLICATE_IP_ENDPOINT_CONFLICT",
    "MISSING_DEFAULT_GATEWAY",
    "OFF_LINK_DEFAULT_GATEWAY",
    "SELF_REFERENCING_GATEWAY",
    # Routing
    "NO_MATCHING_ROUTE",
    "NO_ELIGIBLE_ROUTE",
    "STATIC_NEXT_HOP_INELIGIBLE",
    "NON_FORWARDING_GATEWAY",
    # ARP
    "ARP_NO_RESPONSE",
    "ARP_AMBIGUOUS_RESPONSE",
    "ARP_SAFETY_LIMITED",
    "ARP_RESOLUTION_DEADLINE",
    # ICMP / Ping
    "TTL_EXPIRED",
    "ICMP_ERROR_SUPPRESSED",
    "ICMP_ERROR_DELIVERY_FAILED",
    "ECHO_REQUEST_DROPPED",
    "ECHO_REPLY_DROPPED",
    "ECHO_REPLY_MISMATCH",
    "ECHO_REPLY_DUPLICATE",
    "ECHO_REPLY_LATE",
    "ECHO_TIMEOUT",
    "RETURN_PATH_FAILURE",
    # Execution limits
    "FRAME_BRANCH_TRAVERSAL_LIMIT",
    "REQUEST_EVENT_BUDGET_EXHAUSTED",
    "TEST_EVENT_BUDGET_EXHAUSTED",
    # L2 runtime
    "MAC_FLAPPING_DETECTED",
    "L2_LOOP_OBSERVED",
    # Observation
    "OBSERVATION_TRUNCATED",
    "PENDING_EVENTS_CANCELLED",
    "CONFIGURATION_WARNING_OBSERVED",
}


def test_code_dictionary_matches_contract_exactly():
    assert {member.name for member in DiagnosticCode} == EXPECTED_CODES
    assert len(DiagnosticCode) == len(EXPECTED_CODES) == 34


def test_every_member_value_equals_its_name_and_is_upper_snake_case():
    for member in DiagnosticCode:
        assert member.value == member.name
        assert re.fullmatch(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)*", member.value)


def test_unknown_code_is_rejected_at_the_boundary():
    assert DiagnosticCode("TTL_EXPIRED") is DiagnosticCode.TTL_EXPIRED

    with pytest.raises(ValueError):
        DiagnosticCode("ttl_expired")
    with pytest.raises(ValueError):
        DiagnosticCode("SOMETHING_NEW")


def test_classification_values_match_contract():
    assert {member.value for member in DiagnosticClassification} == {
        "SIMULATION_FAILURE",
        "EXECUTION_LIMIT",
        "WARNING",
        "OBSERVATION",
        "INFORMATION",
    }


def test_direction_values_match_contract():
    assert {member.value for member in Direction} == {
        "FORWARD",
        "RETURN",
        "LOCAL",
        "DIAGNOSTIC",
        "NONE",
    }


def test_evidence_completeness_values_match_contract():
    assert {member.value for member in EvidenceCompleteness} == {
        "COMPLETE",
        "PARTIAL",
        "UNKNOWN",
    }
