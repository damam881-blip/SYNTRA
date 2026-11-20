"""Deterministic ARP resolution windows, ambiguity, late evidence and responder policy."""

import pytest

from app.engine.arp.cache import ArpCache
from app.engine.arp.packet import ArpOperation, build_arp_reply, build_arp_request
from app.engine.arp.resolution import (
    ArpObservationOutcome,
    ArpReplyEvidence,
    ArpResolutionContext,
    ArpResolutionStatus,
    arp_response_for,
    responds_to_arp,
)
from app.engine.clock.queue import ARP_RESOLUTION_WINDOW_NS, ARP_RETRY_INTERVAL_NS
from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.ethernet.mac import parse_mac
from app.engine.ipv4.address import parse_ipv4 as ip
from app.engine.topology.models import DeviceKind

TARGET = ip("192.168.1.20")
MAC_1 = parse_mac("02:00:00:00:00:11")
MAC_2 = parse_mac("02:00:00:00:00:22")


def evidence(
    device_id: str,
    mac: int,
    arrived: int,
    *,
    ip_address: int = TARGET,
    branch: str = "",
    context_id: str = "",
):
    return ArpReplyEvidence(
        responding_device_id=device_id,
        ip=ip_address,
        mac=mac,
        arrived_at_ns=arrived,
        branch_id=branch,
        context_id=context_id,
    )


def test_attempts_and_deadline():
    context = ArpResolutionContext(TARGET, 5_000)

    assert context.deadline_ns == 5_000 + ARP_RESOLUTION_WINDOW_NS
    assert context.attempt_times_ns == (5_000, 5_000 + ARP_RETRY_INTERVAL_NS)


def test_no_response_at_inclusive_deadline():
    context = ArpResolutionContext(TARGET, 0)

    result = context.finalize(ARP_RESOLUTION_WINDOW_NS)

    assert result.status is ArpResolutionStatus.NO_RESPONSE
    assert result.diagnostic_code is DiagnosticCode.ARP_NO_RESPONSE
    assert result.is_finalized and not result.is_success
    assert result.mac is None


def test_in_progress_before_deadline_without_complete_branches():
    context = ArpResolutionContext(TARGET, 0)
    context.expect_branch("b1")

    result = context.finalize(ARP_RESOLUTION_WINDOW_NS - 1)

    assert result.status is ArpResolutionStatus.IN_PROGRESS
    assert not result.is_finalized
    assert context.result is None


def test_single_responder_early_resolves_when_branches_complete():
    context = ArpResolutionContext(TARGET, 0)
    cache = ArpCache()

    assert context.observe(evidence("pc2", MAC_1, 10_000)) is ArpObservationOutcome.ACCEPTED
    result = context.finalize(50_000)

    assert result.status is ArpResolutionStatus.RESOLVED
    assert result.mac == MAC_1
    assert result.evidence_complete
    assert context.apply_to_cache(cache)
    assert cache.lookup(TARGET, 50_000) == MAC_1


def test_single_responder_waits_for_expected_branch():
    context = ArpResolutionContext(TARGET, 0)
    context.expect_branch("slow-branch")
    context.observe(evidence("pc2", MAC_1, 10_000))

    early = context.finalize(10_000)
    late = context.finalize(ARP_RESOLUTION_WINDOW_NS)

    assert early.status is ArpResolutionStatus.IN_PROGRESS
    assert late.status is ArpResolutionStatus.SAFETY_LIMITED
    assert late.diagnostic_code is DiagnosticCode.ARP_SAFETY_LIMITED


def test_reply_at_exactly_deadline_is_accepted():
    context = ArpResolutionContext(TARGET, 0)

    assert (
        context.observe(evidence("pc2", MAC_1, ARP_RESOLUTION_WINDOW_NS))
        is ArpObservationOutcome.ACCEPTED
    )
    result = context.finalize(ARP_RESOLUTION_WINDOW_NS)

    assert result.status is ArpResolutionStatus.RESOLVED


def test_reply_after_deadline_is_late_and_never_reopens():
    context = ArpResolutionContext(TARGET, 0)

    assert (
        context.observe(evidence("pc2", MAC_1, ARP_RESOLUTION_WINDOW_NS + 1))
        is ArpObservationOutcome.LATE
    )
    result = context.finalize(ARP_RESOLUTION_WINDOW_NS + 1)

    assert result.status is ArpResolutionStatus.NO_RESPONSE
    assert context.observe(evidence("pc2", MAC_1, ARP_RESOLUTION_WINDOW_NS + 2)) is (
        ArpObservationOutcome.LATE
    )
    assert context.result is result


def test_evidence_from_before_the_context_start_is_late():
    context = ArpResolutionContext(TARGET, 1_000)

    assert context.observe(evidence("pc2", MAC_1, 999)) is ArpObservationOutcome.LATE
    assert context.finalize(2_000).status is ArpResolutionStatus.NO_RESPONSE


def test_evidence_from_another_context_is_ignored():
    context = ArpResolutionContext(TARGET, 0, context_id="ctx-a")

    foreign = context.observe(evidence("pc2", MAC_1, 1_000, context_id="ctx-b"))
    owned = context.observe(evidence("pc2", MAC_1, 2_000, context_id="ctx-a"))
    result = context.finalize(3_000)

    assert foreign is ArpObservationOutcome.IGNORED
    assert owned is ArpObservationOutcome.ACCEPTED
    assert result.status is ArpResolutionStatus.RESOLVED


def test_duplicate_reply_from_same_device_is_not_ambiguous():
    context = ArpResolutionContext(TARGET, 0)

    context.observe(evidence("pc2", MAC_1, 1_000))
    outcome = context.observe(evidence("pc2", MAC_1, 2_000))
    result = context.finalize(3_000)

    assert outcome is ArpObservationOutcome.DUPLICATE
    assert result.status is ArpResolutionStatus.RESOLVED
    assert len(result.responders) == 1


def test_two_distinct_responders_are_ambiguous_and_do_not_update_cache():
    context = ArpResolutionContext(TARGET, 0)
    cache = ArpCache()

    context.observe(evidence("pc2", MAC_1, 1_000))
    context.observe(evidence("server1", MAC_2, 2_000))
    result = context.finalize(3_000)

    assert result.status is ArpResolutionStatus.AMBIGUOUS
    assert result.diagnostic_code is DiagnosticCode.ARP_AMBIGUOUS_RESPONSE
    assert result.mac is None
    assert not context.apply_to_cache(cache)
    assert cache.lookup(TARGET, 3_000) is None


def test_safety_limited_result_never_updates_cache():
    context = ArpResolutionContext(TARGET, 0)
    cache = ArpCache()
    context.observe(evidence("pc2", MAC_1, 1_000))

    result = context.finalize(ARP_RESOLUTION_WINDOW_NS, safety_limited=True)

    assert result.status is ArpResolutionStatus.SAFETY_LIMITED
    assert not context.apply_to_cache(cache)


def test_evidence_for_another_target_is_ignored():
    context = ArpResolutionContext(TARGET, 0)

    outcome = context.observe(evidence("pc3", MAC_2, 1_000, ip_address=ip("192.168.1.30")))
    result = context.finalize(2_000)

    assert outcome is ArpObservationOutcome.IGNORED
    assert result.status is ArpResolutionStatus.NO_RESPONSE


def test_cache_is_not_mutated_while_context_is_open():
    context = ArpResolutionContext(TARGET, 0)
    cache = ArpCache()
    context.observe(evidence("pc2", MAC_1, 1_000))

    assert not context.apply_to_cache(cache)
    assert cache.lookup(TARGET, 1_000) is None


def test_responder_policy_uses_only_ingress_interface_active_address():
    request = build_arp_request(MAC_1, ip("192.168.1.10"), TARGET)

    assert responds_to_arp(DeviceKind.PC, request, TARGET)
    assert responds_to_arp(DeviceKind.SERVER, request, TARGET)
    assert responds_to_arp(DeviceKind.ROUTER, request, TARGET)
    assert not responds_to_arp(DeviceKind.L2_SWITCH, request, TARGET)
    assert not responds_to_arp(DeviceKind.PC, request, None)
    assert not responds_to_arp(DeviceKind.PC, request, ip("192.168.1.99"))


def test_responder_never_replies_to_a_reply():
    request = build_arp_request(MAC_1, ip("192.168.1.10"), TARGET)
    reply = build_arp_reply(request, MAC_2)

    assert not responds_to_arp(DeviceKind.PC, reply, TARGET)
    assert arp_response_for(DeviceKind.PC, reply, TARGET, MAC_1) is None


def test_arp_response_reverses_sender_and_target():
    request = build_arp_request(MAC_1, ip("192.168.1.10"), TARGET)

    response = arp_response_for(DeviceKind.PC, request, TARGET, MAC_2)

    assert response is not None
    assert response.operation is ArpOperation.REPLY
    assert (response.sender_mac, response.sender_ip) == (MAC_2, TARGET)
    assert (response.target_mac, response.target_ip) == (MAC_1, ip("192.168.1.10"))


@pytest.mark.parametrize("bad_window", [-1, 1.5, True])
def test_invalid_window_is_rejected(bad_window):
    with pytest.raises(ValueError):
        ArpResolutionContext(TARGET, 0, window_ns=bad_window)
