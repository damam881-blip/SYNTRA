"""Semantic Ethernet frame model with the approved TASK-03 V1 sizes.

Only behavior-relevant fields are modeled; byte-level wire encoding is not part of
the approved engine contract. Sizes are the normative totals, including the FCS.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.engine.clock.queue import (
    ARP_FRAME_BYTES,
    ICMP_ECHO_FRAME_BYTES,
    ICMP_TIME_EXCEEDED_FRAME_BYTES,
)
from app.engine.ethernet.mac import InvalidMacAddressError, is_group_address

ETHERNET_HEADER_BYTES = 14
ETHERNET_FCS_BYTES = 4
MIN_ETHERNET_FRAME_BYTES = 64


class FrameKind(StrEnum):
    ARP = "ARP"
    ICMP_ECHO = "ICMP_ECHO"
    ICMP_TIME_EXCEEDED = "ICMP_TIME_EXCEEDED"


FRAME_TOTAL_BYTES: dict[FrameKind, int] = {
    FrameKind.ARP: ARP_FRAME_BYTES,
    FrameKind.ICMP_ECHO: ICMP_ECHO_FRAME_BYTES,
    FrameKind.ICMP_TIME_EXCEEDED: ICMP_TIME_EXCEEDED_FRAME_BYTES,
}


@dataclass(frozen=True, slots=True)
class EthernetFrame:
    """One L2 frame. The payload is an ARP or ICMP message object."""

    destination_mac: int
    source_mac: int
    kind: FrameKind
    payload: object = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FrameKind(self.kind))
        _check_mac("destination_mac", self.destination_mac)
        _check_mac("source_mac", self.source_mac)
        if is_group_address(self.source_mac):
            raise InvalidMacAddressError("frame source MAC cannot be a group address")

    @property
    def total_bytes(self) -> int:
        return FRAME_TOTAL_BYTES[self.kind]

    @property
    def header_bytes(self) -> int:
        return ETHERNET_HEADER_BYTES

    @property
    def fcs_bytes(self) -> int:
        return ETHERNET_FCS_BYTES


def frame_total_bytes(kind: FrameKind) -> int:
    return FRAME_TOTAL_BYTES[FrameKind(kind)]


def _check_mac(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFFFFFF:
        raise InvalidMacAddressError(f"{name} is not a 48-bit MAC value: {value!r}")
