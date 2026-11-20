"""Semantic IPv4 packet model. Integer addresses, deterministic TTL handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from app.engine.ipv4.address import InvalidIPv4AddressError

IPV4_HEADER_BYTES = 20
INITIAL_ECHO_TTL = 16  # T3-DEC-33
MIN_TTL = 0
MAX_TTL = 255


class IpProtocol(IntEnum):
    ICMP = 1


@dataclass(frozen=True, slots=True)
class Ipv4Packet:
    """An IPv4 datagram. The payload is an ICMP message object in V1."""

    source: int
    destination: int
    ttl: int = INITIAL_ECHO_TTL
    protocol: IpProtocol = IpProtocol.ICMP
    payload: object = None

    def __post_init__(self) -> None:
        _check_address("source", self.source)
        _check_address("destination", self.destination)
        if type(self.ttl) is not int or not MIN_TTL <= self.ttl <= MAX_TTL:
            raise ValueError("ttl must be an int between 0 and 255")
        object.__setattr__(self, "protocol", IpProtocol(self.protocol))

    @property
    def header_bytes(self) -> int:
        return IPV4_HEADER_BYTES

    @property
    def expires_on_transit(self) -> bool:
        """True when a router must emit ICMP Time Exceeded instead of forwarding."""
        return self.ttl <= 1

    def is_locally_addressed(self, address: int) -> bool:
        _check_address("address", address)
        return self.destination == address

    def forwarded(self) -> Ipv4Packet:
        """Return the packet a router forwards after decrementing TTL."""
        if self.expires_on_transit:
            raise ValueError("TTL must exceed 1 to forward; emit ICMP Time Exceeded instead")
        return Ipv4Packet(
            source=self.source,
            destination=self.destination,
            ttl=self.ttl - 1,
            protocol=self.protocol,
            payload=self.payload,
        )


def build_ipv4_packet(
    source: int,
    destination: int,
    payload: object = None,
    *,
    ttl: int = INITIAL_ECHO_TTL,
) -> Ipv4Packet:
    return Ipv4Packet(
        source=source,
        destination=destination,
        ttl=ttl,
        protocol=IpProtocol.ICMP,
        payload=payload,
    )


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")
