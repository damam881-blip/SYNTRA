"""Host forwarding decision: direct ARP target versus default gateway (TASK-03 §4.2).

Only a PC or Server has a host default gateway. Routers use their routing table.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.ipv4.address import (
    InvalidIPv4AddressError,
    InvalidSubnetMaskError,
    is_contiguous_mask,
    same_subnet,
)


class HostForwardingStatus(StrEnum):
    LOCAL = "LOCAL"
    DIRECT = "DIRECT"
    VIA_GATEWAY = "VIA_GATEWAY"
    SOURCE_IPV4_UNCONFIGURED = "SOURCE_IPV4_UNCONFIGURED"
    MISSING_DEFAULT_GATEWAY = "MISSING_DEFAULT_GATEWAY"
    OFF_LINK_DEFAULT_GATEWAY = "OFF_LINK_DEFAULT_GATEWAY"
    SELF_REFERENCING_GATEWAY = "SELF_REFERENCING_GATEWAY"


@dataclass(frozen=True, slots=True)
class HostForwardingDecision:
    status: HostForwardingStatus
    destination: int
    next_hop: int | None = None

    @property
    def requires_arp(self) -> bool:
        return self.status in (HostForwardingStatus.DIRECT, HostForwardingStatus.VIA_GATEWAY)

    @property
    def is_usable(self) -> bool:
        return self.status in (
            HostForwardingStatus.LOCAL,
            HostForwardingStatus.DIRECT,
            HostForwardingStatus.VIA_GATEWAY,
        )

    @property
    def diagnostic_code(self) -> DiagnosticCode | None:
        return _DIAGNOSTIC_CODES.get(self.status)


_DIAGNOSTIC_CODES: dict[HostForwardingStatus, DiagnosticCode] = {
    HostForwardingStatus.SOURCE_IPV4_UNCONFIGURED: DiagnosticCode.SOURCE_IPV4_UNCONFIGURED,
    HostForwardingStatus.MISSING_DEFAULT_GATEWAY: DiagnosticCode.MISSING_DEFAULT_GATEWAY,
    HostForwardingStatus.OFF_LINK_DEFAULT_GATEWAY: DiagnosticCode.OFF_LINK_DEFAULT_GATEWAY,
    HostForwardingStatus.SELF_REFERENCING_GATEWAY: DiagnosticCode.SELF_REFERENCING_GATEWAY,
}


def decide_host_forwarding(
    destination: int,
    *,
    source_address: int | None,
    mask: int | None,
    gateway: int | None = None,
) -> HostForwardingDecision:
    """Decide the L3 next hop for a PC/Server before ARP."""
    _check_address("destination", destination)
    if (source_address is None) != (mask is None):
        raise ValueError("source_address and mask must be configured or cleared together")
    if source_address is None:
        return HostForwardingDecision(HostForwardingStatus.SOURCE_IPV4_UNCONFIGURED, destination)

    assert mask is not None
    _check_mask(mask)
    if destination == source_address:
        return HostForwardingDecision(HostForwardingStatus.LOCAL, destination)

    if same_subnet(destination, source_address, mask):
        return HostForwardingDecision(HostForwardingStatus.DIRECT, destination, destination)

    if gateway is None:
        return HostForwardingDecision(HostForwardingStatus.MISSING_DEFAULT_GATEWAY, destination)
    _check_address("gateway", gateway)
    if gateway == source_address:
        return HostForwardingDecision(HostForwardingStatus.SELF_REFERENCING_GATEWAY, destination)
    if not same_subnet(gateway, source_address, mask):
        return HostForwardingDecision(HostForwardingStatus.OFF_LINK_DEFAULT_GATEWAY, destination)

    return HostForwardingDecision(HostForwardingStatus.VIA_GATEWAY, destination, gateway)


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")


def _check_mask(mask: int) -> None:
    if not is_contiguous_mask(mask):
        raise InvalidSubnetMaskError(f"not a contiguous 32-bit mask: {mask!r}")
