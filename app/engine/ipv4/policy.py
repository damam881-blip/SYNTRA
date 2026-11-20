"""IPv4 configuration policy for hosts, gateways, routes and next hops.

Pure integer logic. Structural rules come from TASK-02 §3.1A; runtime gateway
eligibility comes from TASK-03 §4.2. Functions return a problem value instead of
raising so callers can attach stable diagnostic evidence.
"""

from enum import StrEnum

from app.engine.ipv4.address import (
    HostAddressProblem,
    host_address_problem,
    network_address,
    parse_ipv4,
    parse_subnet_mask,
    prefix_mask,
    same_subnet,
    special_address_problem,
)


class GatewayProblem(StrEnum):
    """Why a stored host gateway cannot be used for forwarding."""

    EXCLUDED_ADDRESS = "EXCLUDED_ADDRESS"
    LIMITED_BROADCAST = "LIMITED_BROADCAST"
    SELF_REFERENCING = "SELF_REFERENCING"
    OFF_LINK = "OFF_LINK"


class RouteDestinationProblem(StrEnum):
    """Structural reasons a static-route destination is malformed."""

    PREFIX_OUT_OF_RANGE = "PREFIX_OUT_OF_RANGE"
    NONCANONICAL_NETWORK = "NONCANONICAL_NETWORK"


def gateway_problem(
    gateway: int,
    host_address: int | None,
    mask: int | None,
) -> GatewayProblem | None:
    """Return the structural/runtime problem with a host gateway, or None.

    When host IPv4 is missing the on-link check is deferred, exactly as TASK-02
    requires: the gateway may be stored but remains inactive.
    """
    special = special_address_problem(gateway)
    if special == HostAddressProblem.LIMITED_BROADCAST:
        return GatewayProblem.LIMITED_BROADCAST
    if special is not None:
        return GatewayProblem.EXCLUDED_ADDRESS

    if host_address is None or mask is None:
        return None
    if gateway == host_address:
        return GatewayProblem.SELF_REFERENCING
    if not same_subnet(gateway, host_address, mask):
        return GatewayProblem.OFF_LINK
    return None


def route_destination_problem(
    destination: int, prefix_length: int
) -> RouteDestinationProblem | None:
    """Validate a static-route destination network (mask is derived from the prefix)."""
    if type(prefix_length) is not int or not 0 <= prefix_length <= 32:
        return RouteDestinationProblem.PREFIX_OUT_OF_RANGE
    if destination != network_address(destination, prefix_mask(prefix_length)):
        return RouteDestinationProblem.NONCANONICAL_NETWORK
    return None


def next_hop_problem(next_hop: int) -> HostAddressProblem | None:
    """Special-use addresses cannot be a static next hop (TASK-02 §3.1A)."""
    return special_address_problem(next_hop)


def is_valid_host_interface(address: int, mask: int) -> bool:
    return host_address_problem(address, mask) is None


def gateway_from_text(
    gateway_text: str,
    host_address_text: str | None,
    mask_text: str | None,
) -> GatewayProblem | None:
    """Parse-and-check convenience for the configuration boundary."""
    gateway = parse_ipv4(gateway_text)
    host_address = None if host_address_text is None else parse_ipv4(host_address_text)
    mask = None if mask_text is None else parse_subnet_mask(mask_text)
    return gateway_problem(gateway, host_address, mask)
