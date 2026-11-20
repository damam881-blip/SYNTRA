"""Semantic ICMP messages and Echo Reply correlation (TASK-03 §4.2, §4.3)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from app.engine.ipv4.address import (
    HostAddressProblem,
    InvalidIPv4AddressError,
    special_address_problem,
)

ECHO_PAYLOAD_BYTES = 32
ICMP_HEADER_BYTES = 8
TIME_EXCEEDED_QUOTE_BYTES = 8
MAX_IDENTIFIER = 0xFFFF
REQUEST_SEQUENCE_MIN = 1
REQUEST_SEQUENCE_MAX = 4


class IcmpType(IntEnum):
    ECHO_REPLY = 0
    ECHO_REQUEST = 8
    TIME_EXCEEDED = 11


@dataclass(frozen=True, slots=True)
class EchoMessage:
    """A semantic ICMP Echo Request/Reply with the approved 32-byte payload."""

    icmp_type: IcmpType
    identifier: int
    sequence: int
    source: int
    destination: int
    payload_bytes: int = ECHO_PAYLOAD_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "icmp_type", IcmpType(self.icmp_type))
        if self.icmp_type not in (IcmpType.ECHO_REQUEST, IcmpType.ECHO_REPLY):
            raise ValueError("EchoMessage type must be Echo Request or Echo Reply")
        if type(self.identifier) is not int or not 0 <= self.identifier <= MAX_IDENTIFIER:
            raise ValueError("identifier must be a 16-bit int")
        if type(self.sequence) is not int or not 0 <= self.sequence <= MAX_IDENTIFIER:
            raise ValueError("sequence must be a 16-bit int")
        _check_address("source", self.source)
        _check_address("destination", self.destination)
        if self.payload_bytes != ECHO_PAYLOAD_BYTES:
            raise ValueError(f"Echo payload must be {ECHO_PAYLOAD_BYTES} bytes in V1")

    @property
    def is_request(self) -> bool:
        return self.icmp_type == IcmpType.ECHO_REQUEST

    @property
    def is_reply(self) -> bool:
        return self.icmp_type == IcmpType.ECHO_REPLY

    def as_reply(self) -> EchoMessage:
        """Create the matching Echo Reply: type 0 and reversed addresses."""
        if not self.is_request:
            raise ValueError("only an Echo Request can be converted to an Echo Reply")
        return EchoMessage(
            icmp_type=IcmpType.ECHO_REPLY,
            identifier=self.identifier,
            sequence=self.sequence,
            source=self.destination,
            destination=self.source,
        )


@dataclass(frozen=True, slots=True)
class TimeExceededMessage:
    """ICMP type 11 code 0 quoting the original IPv4 header and first 8 bytes."""

    source: int
    destination: int
    original_source: int
    original_destination: int
    original_ttl: int
    quote_bytes: int = TIME_EXCEEDED_QUOTE_BYTES

    def __post_init__(self) -> None:
        for name in ("source", "destination", "original_source", "original_destination"):
            _check_address(name, getattr(self, name))
        if type(self.original_ttl) is not int or not 0 <= self.original_ttl <= 255:
            raise ValueError("original_ttl must be an int between 0 and 255")
        if self.quote_bytes != TIME_EXCEEDED_QUOTE_BYTES:
            raise ValueError(f"Time Exceeded quote must be {TIME_EXCEEDED_QUOTE_BYTES} bytes")

    @property
    def icmp_type(self) -> IcmpType:
        return IcmpType.TIME_EXCEEDED

    @property
    def code(self) -> int:
        return 0

    @property
    def is_icmp_error(self) -> bool:
        return True


def build_echo_request(
    source: int,
    destination: int,
    *,
    identifier: int,
    sequence: int,
) -> EchoMessage:
    if not REQUEST_SEQUENCE_MIN <= sequence <= REQUEST_SEQUENCE_MAX:
        raise ValueError(
            f"Echo Request sequence must be {REQUEST_SEQUENCE_MIN}..{REQUEST_SEQUENCE_MAX}"
        )
    return EchoMessage(
        icmp_type=IcmpType.ECHO_REQUEST,
        identifier=identifier,
        sequence=sequence,
        source=source,
        destination=destination,
    )


def build_time_exceeded(
    *,
    router_address: int,
    original_source: int,
    original_destination: int,
    original_ttl: int,
) -> TimeExceededMessage:
    return TimeExceededMessage(
        source=router_address,
        destination=original_source,
        original_source=original_source,
        original_destination=original_destination,
        original_ttl=original_ttl,
    )


@dataclass(frozen=True, slots=True)
class RequestCorrelation:
    """Internal per-test identity attached to one logical Echo Request."""

    test_id: int
    sequence: int
    source: int
    destination: int
    request_id: str = ""

    def __post_init__(self) -> None:
        if type(self.test_id) is not int or not 0 <= self.test_id <= MAX_IDENTIFIER:
            raise ValueError("test_id must be a 16-bit int")
        if not REQUEST_SEQUENCE_MIN <= self.sequence <= REQUEST_SEQUENCE_MAX:
            raise ValueError("sequence must be 1..4")
        _check_address("source", self.source)
        _check_address("destination", self.destination)
        if not isinstance(self.request_id, str):
            raise TypeError("request_id must be a string")

    @property
    def key(self) -> tuple[int, int]:
        return (self.test_id, self.sequence)


class ReplyMatchOutcome(StrEnum):
    MATCHED = "MATCHED"
    DUPLICATE = "DUPLICATE"
    MISMATCH = "MISMATCH"


class EchoReplyCorrelator:
    """Accept at most one matching Echo Reply per logical request."""

    def __init__(self) -> None:
        self._matched: set[tuple[int, int]] = set()

    def match(self, reply: EchoMessage, request: RequestCorrelation) -> ReplyMatchOutcome:
        if not isinstance(reply, EchoMessage) or not reply.is_reply:
            return ReplyMatchOutcome.MISMATCH
        if reply.identifier != request.test_id or reply.sequence != request.sequence:
            return ReplyMatchOutcome.MISMATCH
        if reply.source != request.destination or reply.destination != request.source:
            return ReplyMatchOutcome.MISMATCH
        if request.key in self._matched:
            return ReplyMatchOutcome.DUPLICATE
        self._matched.add(request.key)
        return ReplyMatchOutcome.MATCHED

    def is_matched(self, request: RequestCorrelation) -> bool:
        return request.key in self._matched

    @property
    def matched_count(self) -> int:
        return len(self._matched)


def icmp_error_allowed(destination: int, triggering_payload: object) -> bool:
    """ICMP errors are never sent to non-unicast addresses or in response to an ICMP error."""
    _check_address("destination", destination)
    special = special_address_problem(destination)
    if special in (HostAddressProblem.EXCLUDED_ADDRESS, HostAddressProblem.LIMITED_BROADCAST):
        return False
    if isinstance(triggering_payload, TimeExceededMessage):
        return False
    return True


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")
