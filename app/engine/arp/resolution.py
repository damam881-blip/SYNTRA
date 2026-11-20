"""Deterministic ARP resolution contexts (TASK-03 §4.4, T3-DEC-43..47, 53..56).

A context exists for one resolution window of at most 200 ms. Replies are evidence:
the cache is updated only by an accepted RESOLVED context, and late evidence can
never reopen a finalized resolution.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.engine.arp.cache import ArpCache
from app.engine.arp.packet import ArpMessage, build_arp_reply
from app.engine.clock.queue import ARP_RESOLUTION_WINDOW_NS, ARP_RETRY_INTERVAL_NS
from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.ethernet.mac import InvalidMacAddressError, is_group_address
from app.engine.ipv4.address import InvalidIPv4AddressError
from app.engine.topology.models import DeviceKind


class ArpResolutionStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_RESPONSE = "NO_RESPONSE"
    SAFETY_LIMITED = "SAFETY_LIMITED"


class ArpObservationOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    LATE = "LATE"


@dataclass(frozen=True, slots=True)
class ArpReplyEvidence:
    """One delivered ARP reply candidate for a resolution target."""

    responding_device_id: str
    ip: int
    mac: int
    arrived_at_ns: int
    branch_id: str = ""
    branch_complete: bool = True
    context_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.responding_device_id, str) or not self.responding_device_id:
            raise ValueError("responding_device_id must be a non-empty string")
        _check_address("ip", self.ip)
        _check_mac("mac", self.mac)
        if is_group_address(self.mac):
            raise InvalidMacAddressError("ARP responder MAC must be unicast")
        if type(self.arrived_at_ns) is not int or self.arrived_at_ns < 0:
            raise ValueError("arrived_at_ns must be a non-negative int")
        if not isinstance(self.branch_id, str):
            raise TypeError("branch_id must be a string")
        if not isinstance(self.context_id, str):
            raise TypeError("context_id must be a string")


@dataclass(frozen=True, slots=True)
class ArpResolutionResult:
    status: ArpResolutionStatus
    target_ip: int
    mac: int | None
    responders: tuple[ArpReplyEvidence, ...]
    deadline_ns: int
    finalized_at_ns: int
    evidence_complete: bool

    @property
    def is_finalized(self) -> bool:
        return self.status != ArpResolutionStatus.IN_PROGRESS

    @property
    def is_success(self) -> bool:
        return self.status == ArpResolutionStatus.RESOLVED

    @property
    def diagnostic_code(self) -> DiagnosticCode | None:
        return _DIAGNOSTIC_CODES.get(self.status)


_DIAGNOSTIC_CODES: dict[ArpResolutionStatus, DiagnosticCode] = {
    ArpResolutionStatus.AMBIGUOUS: DiagnosticCode.ARP_AMBIGUOUS_RESPONSE,
    ArpResolutionStatus.NO_RESPONSE: DiagnosticCode.ARP_NO_RESPONSE,
    ArpResolutionStatus.SAFETY_LIMITED: DiagnosticCode.ARP_SAFETY_LIMITED,
}


class ArpResolutionContext:
    """One ownership-scoped ARP resolution for a target IPv4 address."""

    def __init__(
        self,
        target_ip: int,
        started_at_ns: int,
        *,
        window_ns: int = ARP_RESOLUTION_WINDOW_NS,
        retry_interval_ns: int = ARP_RETRY_INTERVAL_NS,
        context_id: str = "",
    ) -> None:
        _check_address("target_ip", target_ip)
        if type(started_at_ns) is not int or started_at_ns < 0:
            raise ValueError("started_at_ns must be a non-negative int")
        if type(window_ns) is not int or window_ns < 0:
            raise ValueError("window_ns must be a non-negative int")
        if type(retry_interval_ns) is not int or retry_interval_ns < 0:
            raise ValueError("retry_interval_ns must be a non-negative int")
        if not isinstance(context_id, str):
            raise TypeError("context_id must be a string")

        self.target_ip = target_ip
        self.started_at_ns = started_at_ns
        self.window_ns = window_ns
        self.retry_interval_ns = retry_interval_ns
        self.context_id = context_id
        self._responders: dict[tuple[str, int], ArpReplyEvidence] = {}
        self._expected_branches: set[str] = set()
        self._completed_branches: set[str] = set()
        self._result: ArpResolutionResult | None = None

    @property
    def deadline_ns(self) -> int:
        return self.started_at_ns + self.window_ns

    @property
    def attempt_times_ns(self) -> tuple[int, ...]:
        """Two attempts: at start and at start + 100 ms (T3-DEC-43)."""
        second = self.started_at_ns + self.retry_interval_ns
        if second > self.deadline_ns:
            return (self.started_at_ns,)
        return (self.started_at_ns, second)

    @property
    def responders(self) -> tuple[ArpReplyEvidence, ...]:
        return tuple(self._responders.values())

    @property
    def result(self) -> ArpResolutionResult | None:
        return self._result

    @property
    def is_finalized(self) -> bool:
        return self._result is not None

    def expect_branch(self, branch_id: str) -> None:
        self._expected_branches.add(_check_branch(branch_id))

    def complete_branch(self, branch_id: str) -> None:
        self._completed_branches.add(_check_branch(branch_id))

    @property
    def branches_complete(self) -> bool:
        return self._expected_branches <= self._completed_branches

    def observe(self, evidence: ArpReplyEvidence) -> ArpObservationOutcome:
        if not isinstance(evidence, ArpReplyEvidence):
            raise TypeError("evidence must be an ArpReplyEvidence")
        if (
            self.is_finalized
            or evidence.arrived_at_ns < self.started_at_ns
            or evidence.arrived_at_ns > self.deadline_ns
        ):
            return ArpObservationOutcome.LATE
        if evidence.context_id and self.context_id and evidence.context_id != self.context_id:
            return ArpObservationOutcome.IGNORED
        if evidence.ip != self.target_ip:
            return ArpObservationOutcome.IGNORED

        if evidence.branch_id:
            self.complete_branch(evidence.branch_id)

        key = (evidence.responding_device_id, evidence.mac)
        if key in self._responders:
            return ArpObservationOutcome.DUPLICATE
        self._responders[key] = evidence
        return ArpObservationOutcome.ACCEPTED

    def finalize(
        self,
        now_ns: int,
        *,
        all_branches_complete: bool | None = None,
        safety_limited: bool = False,
    ) -> ArpResolutionResult:
        """Close the context when evidence is complete or the deadline is due."""
        if type(now_ns) is not int or now_ns < self.started_at_ns:
            raise ValueError("now_ns must be an int at or after started_at_ns")
        if self._result is not None:
            return self._result

        complete = (
            self.branches_complete if all_branches_complete is None else all_branches_complete
        )

        if not safety_limited and now_ns < self.deadline_ns and not complete:
            return self._in_progress(complete)

        if safety_limited:
            status = ArpResolutionStatus.SAFETY_LIMITED
        elif not complete:
            status = ArpResolutionStatus.SAFETY_LIMITED
        elif len(self._responders) == 1:
            status = ArpResolutionStatus.RESOLVED
        elif len(self._responders) > 1:
            status = ArpResolutionStatus.AMBIGUOUS
        else:
            status = ArpResolutionStatus.NO_RESPONSE

        resolved_mac = (
            next(iter(self._responders.values())).mac
            if status is ArpResolutionStatus.RESOLVED
            else None
        )
        result = ArpResolutionResult(
            status=status,
            target_ip=self.target_ip,
            mac=resolved_mac,
            responders=self.responders,
            deadline_ns=self.deadline_ns,
            finalized_at_ns=now_ns,
            evidence_complete=complete,
        )
        self._result = result
        return result

    def apply_to_cache(self, cache: ArpCache) -> bool:
        """Learn into the ARP cache only from an accepted RESOLVED context."""
        if not isinstance(cache, ArpCache):
            raise TypeError("cache must be an ArpCache")
        if self._result is None or not self._result.is_success:
            return False
        assert self._result.mac is not None
        cache.update(self.target_ip, self._result.mac, self._result.finalized_at_ns)
        return True

    def _in_progress(self, complete: bool) -> ArpResolutionResult:
        return ArpResolutionResult(
            status=ArpResolutionStatus.IN_PROGRESS,
            target_ip=self.target_ip,
            mac=None,
            responders=self.responders,
            deadline_ns=self.deadline_ns,
            finalized_at_ns=self.started_at_ns,
            evidence_complete=complete,
        )


def responds_to_arp(
    device_kind: DeviceKind | str,
    request: ArpMessage,
    ingress_interface_address: int | None,
) -> bool:
    """ARP responder policy: no switch replies, no proxy ARP, active ingress IP only."""
    if not isinstance(request, ArpMessage):
        raise TypeError("request must be an ArpMessage")
    if not request.is_request:
        return False
    if DeviceKind(device_kind) is DeviceKind.L2_SWITCH:
        return False
    if ingress_interface_address is None:
        return False
    return request.target_ip == ingress_interface_address


def arp_response_for(
    device_kind: DeviceKind | str,
    request: ArpMessage,
    ingress_interface_address: int | None,
    responder_mac: int,
) -> ArpMessage | None:
    if not responds_to_arp(device_kind, request, ingress_interface_address):
        return None
    return build_arp_reply(request, responder_mac)


def _check_branch(branch_id: str) -> str:
    if not isinstance(branch_id, str) or not branch_id:
        raise ValueError("branch_id must be a non-empty string")
    return branch_id


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")


def _check_mac(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFFFFFF:
        raise InvalidMacAddressError(f"{name} is not a 48-bit MAC value: {value!r}")
