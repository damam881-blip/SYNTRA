"""TASK-02 §3.1A IPv4 host, gateway, route and next-hop policy."""

import pytest

from app.engine.ipv4.address import (
    HostAddressProblem,
    host_address_problem,
)
from app.engine.ipv4.address import (
    parse_ipv4 as ip,
)
from app.engine.ipv4.address import (
    parse_subnet_mask as mask,
)
from app.engine.ipv4.policy import (
    GatewayProblem,
    RouteDestinationProblem,
    gateway_from_text,
    gateway_problem,
    is_valid_host_interface,
    next_hop_problem,
    route_destination_problem,
)


@pytest.mark.parametrize(
    "address",
    ["0.0.0.1", "127.0.0.1", "169.254.10.1", "224.0.0.1", "239.255.255.255", "240.0.0.1"],
)
def test_special_use_addresses_are_excluded(address):
    assert host_address_problem(ip(address), mask("255.255.255.0")) in (
        HostAddressProblem.EXCLUDED_ADDRESS,
        HostAddressProblem.BROADCAST_ADDRESS,
    )


def test_limited_broadcast_is_reported_separately():
    assert (
        host_address_problem(ip("255.255.255.255"), mask("255.255.255.0"))
        == HostAddressProblem.LIMITED_BROADCAST
    )


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "100.64.0.1", "172.16.5.5", "192.168.1.10", "198.51.100.1"],
)
def test_unicast_and_default_allow_ranges_are_accepted(address):
    assert host_address_problem(ip(address), mask("255.255.255.0")) is None


def test_host_prefix_and_role_boundaries():
    assert host_address_problem(ip("10.0.0.1"), mask("128.0.0.0")) is None
    assert host_address_problem(ip("10.0.0.1"), mask("255.255.255.252")) is None
    assert (
        host_address_problem(ip("10.0.0.1"), mask("255.255.255.254"))
        == HostAddressProblem.UNSUPPORTED_PREFIX_LENGTH
    )
    assert (
        host_address_problem(ip("10.0.0.1"), mask("255.255.255.255"))
        == HostAddressProblem.UNSUPPORTED_PREFIX_LENGTH
    )
    assert (
        host_address_problem(ip("10.0.0.0"), mask("255.255.255.0"))
        == HostAddressProblem.NETWORK_ADDRESS
    )
    assert (
        host_address_problem(ip("10.0.0.255"), mask("255.255.255.0"))
        == HostAddressProblem.BROADCAST_ADDRESS
    )
    assert is_valid_host_interface(ip("10.0.0.1"), mask("255.255.255.0"))
    assert not is_valid_host_interface(ip("10.0.0.0"), mask("255.255.255.0"))


def test_gateway_on_link_and_self_reference():
    host = ip("192.168.10.10")
    subnet = mask("255.255.255.0")

    assert gateway_problem(ip("192.168.10.1"), host, subnet) is None
    assert gateway_problem(host, host, subnet) == GatewayProblem.SELF_REFERENCING
    assert gateway_problem(ip("192.168.20.1"), host, subnet) == GatewayProblem.OFF_LINK


def test_gateway_special_use_is_rejected():
    host = ip("192.168.10.10")
    subnet = mask("255.255.255.0")

    assert gateway_problem(ip("127.0.0.1"), host, subnet) == GatewayProblem.EXCLUDED_ADDRESS
    assert gateway_problem(ip("0.0.0.0"), host, subnet) == GatewayProblem.EXCLUDED_ADDRESS
    assert gateway_problem(ip("255.255.255.255"), host, subnet) == GatewayProblem.LIMITED_BROADCAST


def test_gateway_on_link_check_is_deferred_without_host_ipv4():
    assert gateway_problem(ip("10.99.99.1"), None, None) is None
    assert gateway_from_text("10.99.99.1", None, None) is None
    assert gateway_from_text("192.168.1.1", "192.168.1.10", "255.255.255.0") is None
    assert gateway_from_text("10.0.0.1", "192.168.1.10", "255.255.255.0") == GatewayProblem.OFF_LINK


def test_route_destination_must_be_canonical():
    assert route_destination_problem(ip("10.0.0.0"), 24) is None
    assert route_destination_problem(ip("0.0.0.0"), 0) is None
    assert (
        route_destination_problem(ip("10.0.0.9"), 24)
        == RouteDestinationProblem.NONCANONICAL_NETWORK
    )
    assert (
        route_destination_problem(ip("10.0.0.0"), 33) == RouteDestinationProblem.PREFIX_OUT_OF_RANGE
    )


def test_next_hop_special_use_is_rejected():
    assert next_hop_problem(ip("192.168.1.1")) is None
    assert next_hop_problem(ip("224.0.0.1")) == HostAddressProblem.EXCLUDED_ADDRESS
    assert next_hop_problem(ip("255.255.255.255")) == HostAddressProblem.LIMITED_BROADCAST
    assert next_hop_problem(ip("169.254.1.1")) == HostAddressProblem.EXCLUDED_ADDRESS
