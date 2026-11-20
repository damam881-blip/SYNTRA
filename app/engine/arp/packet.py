"""Semantic ARP messages (TASK-03 §4.4). No wire encoding is modeled."""

from dataclasses import dataclass
from enum import IntEnum

from app.engine.ethernet.mac import BROADCAST_MAC, InvalidMacAddressError, is_group_address
from app.engine.ipv4.address import InvalidIPv4AddressError


class ArpOperation(IntEnum):
    REQUEST = 1
    REPLY = 2


@dataclass(frozen=True, slots=True)
class ArpMessage:
    operation: ArpOperation
    sender_mac: int
    sender_ip: int
    target_ip: int
    target_mac: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", ArpOperation(self.operation))
        _check_mac("sender_mac", self.sender_mac)
        if is_group_address(self.sender_mac):
            raise InvalidMacAddressError("ARP sender MAC must be unicast")
        _check_address("sender_ip", self.sender_ip)
        _check_address("target_ip", self.target_ip)
        if self.target_mac is not None:
            _check_mac("target_mac", self.target_mac)
        if self.operation == ArpOperation.REPLY and self.target_mac is None:
            raise ValueError("ARP reply must carry the target hardware address")

    @property
    def is_request(self) -> bool:
        return self.operation == ArpOperation.REQUEST

    @property
    def is_reply(self) -> bool:
        return self.operation == ArpOperation.REPLY


def build_arp_request(sender_mac: int, sender_ip: int, target_ip: int) -> ArpMessage:
    return ArpMessage(
        operation=ArpOperation.REQUEST,
        sender_mac=sender_mac,
        sender_ip=sender_ip,
        target_ip=target_ip,
        target_mac=None,
    )


def build_arp_reply(request: ArpMessage, responder_mac: int) -> ArpMessage:
    """Reply to `request` for its target IP, with reversed sender/target fields."""
    if not request.is_request:
        raise ValueError("an ARP reply can only answer an ARP request")
    return ArpMessage(
        operation=ArpOperation.REPLY,
        sender_mac=responder_mac,
        sender_ip=request.target_ip,
        target_ip=request.sender_ip,
        target_mac=request.sender_mac,
    )


def request_frame_destination_mac(request: ArpMessage) -> int:
    """ARP requests are broadcast at L2 in the approved V1 model."""
    if not request.is_request:
        raise ValueError("only ARP requests use the broadcast destination MAC")
    return BROADCAST_MAC


def _check_mac(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFFFFFF:
        raise InvalidMacAddressError(f"{name} is not a 48-bit MAC value: {value!r}")


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")
