"""Deterministic router forwarding decisions (TASK-03 §4.1A)."""

import pytest

from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.ipv4.address import InvalidIPv4AddressError
from app.engine.ipv4.address import parse_ipv4 as ip
from app.engine.routing.decision import (
    RouteDecisionStatus,
    RouteKind,
    RouterForwardingTable,
    RouterInterface,
    StaticRouteConfig,
)


def interface(
    interface_id,
    ordinal,
    address=None,
    prefix=None,
    *,
    admin=True,
    link=True,
    device_id="r1",
    device_sequence=1,
):
    return RouterInterface(
        interface_id=interface_id,
        device_id=device_id,
        ordinal=ordinal,
        device_sequence=device_sequence,
        address=None if address is None else ip(address),
        prefix_length=prefix,
        admin_enabled=admin,
        link_operational=link,
    )


def route(route_id, destination, prefix, next_hop, sequence, metric=1):
    return StaticRouteConfig(route_id, ip(destination), prefix, ip(next_hop), sequence, metric)


def rt03_table():
    return RouterForwardingTable(
        [
            interface("i0", 0, "192.168.10.1", 24),
            interface("i1", 1, "192.168.20.1", 24),
        ]
    )


def test_connected_route_forwards_to_destination_interface():
    decision = rt03_table().decide(ip("192.168.20.10"), ttl=16)

    assert decision.status is RouteDecisionStatus.FORWARD
    assert decision.is_forwarded and not decision.is_local
    assert decision.selected is not None
    assert decision.selected.kind is RouteKind.CONNECTED
    assert decision.selected.prefix_length == 24
    assert decision.egress_interface_id == "i1"
    assert decision.next_hop == ip("192.168.20.10")


def test_local_delivery_precedes_ttl_expiry():
    decision = rt03_table().decide(ip("192.168.10.1"), ttl=1)

    assert decision.status is RouteDecisionStatus.LOCAL_DELIVERY
    assert decision.is_local
    assert decision.next_hop is None


def test_ttl_expiry_precedes_route_lookup():
    decision = rt03_table().decide(ip("10.99.99.99"), ttl=1)

    assert decision.status is RouteDecisionStatus.TTL_EXPIRED
    assert decision.diagnostic_code is DiagnosticCode.TTL_EXPIRED
    assert decision.matched_candidates == ()


def test_no_matching_route_is_distinct_from_no_eligible_route():
    no_match = rt03_table().decide(ip("10.99.99.99"), ttl=16)
    assert no_match.status is RouteDecisionStatus.NO_MATCHING_ROUTE
    assert no_match.diagnostic_code is DiagnosticCode.NO_MATCHING_ROUTE

    table = RouterForwardingTable([interface("i0", 0, "192.168.10.1", 24, admin=False)])
    no_eligible = table.decide(ip("192.168.10.10"), ttl=16)
    assert no_eligible.status is RouteDecisionStatus.NO_ELIGIBLE_ROUTE
    assert no_eligible.diagnostic_code is DiagnosticCode.NO_ELIGIBLE_ROUTE
    assert len(no_eligible.ineligible_candidates) == 1


def test_static_longest_prefix_wins_over_default():
    table = RouterForwardingTable(
        [
            interface("i0", 0, "192.168.10.1", 24),
            interface("i1", 1, "192.168.20.1", 24),
        ],
        [
            route("default", "0.0.0.0", 0, "192.168.10.254", 1),
            route("ten", "10.1.0.0", 16, "192.168.20.254", 2),
        ],
    )

    specific = table.decide(ip("10.1.2.3"), ttl=16)
    default = table.decide(ip("8.8.8.8"), ttl=16)

    assert specific.selected.source_id == "ten"
    assert specific.next_hop == ip("192.168.20.254")
    assert specific.egress_interface_id == "i1"
    assert default.selected.source_id == "default"


def test_ineligible_static_falls_back_to_less_specific_route():
    table = RouterForwardingTable(
        [interface("i0", 0, "192.168.10.1", 24)],
        [
            route("unreachable", "10.1.0.0", 16, "172.16.0.1", 2),
            route("default", "0.0.0.0", 0, "192.168.10.254", 1),
        ],
    )

    decision = table.decide(ip("10.1.2.3"), ttl=16)

    assert decision.selected.source_id == "default"
    assert [candidate.source_id for candidate in decision.ineligible_candidates] == ["unreachable"]
    assert decision.ineligible_candidates[0].ineligible_reason is (
        DiagnosticCode.STATIC_NEXT_HOP_INELIGIBLE
    )


def test_ineligible_static_over_connected_route_uses_less_specific_connected():
    table = RouterForwardingTable(
        [interface("i0", 0, "10.1.0.1", 16)],
        [route("bogus", "10.1.2.0", 24, "172.16.0.1", 1)],
    )

    decision = table.decide(ip("10.1.2.3"), ttl=16)

    assert decision.selected.kind is RouteKind.CONNECTED
    assert decision.selected.prefix_length == 16
    assert decision.egress_interface_id == "i0"


def test_static_next_hop_cannot_be_a_local_router_address():
    table = RouterForwardingTable(
        [interface("i0", 0, "192.168.10.1", 24)],
        [route("self", "10.1.0.0", 16, "192.168.10.1", 1)],
    )

    decision = table.decide(ip("10.1.2.3"), ttl=16)

    assert decision.status is RouteDecisionStatus.NO_ELIGIBLE_ROUTE
    assert decision.ineligible_candidates[0].source_id == "self"
    assert decision.ineligible_candidates[0].ineligible_reason is (
        DiagnosticCode.STATIC_NEXT_HOP_INELIGIBLE
    )


def test_connected_wins_over_static_at_equal_prefix_and_metric():
    table = RouterForwardingTable(
        [
            interface("i0", 0, "10.0.0.1", 24),
            interface("i1", 1, "192.168.10.1", 24),
        ],
        [route("static", "10.0.0.0", 24, "192.168.10.254", 1)],
    )

    decision = table.decide(ip("10.0.0.9"), ttl=16)

    assert decision.selected.kind is RouteKind.CONNECTED
    assert decision.egress_interface_id == "i0"


def test_static_tie_uses_immutable_creation_order():
    table = RouterForwardingTable(
        [interface("i0", 0, "192.168.10.1", 24)],
        [
            route("later", "10.1.0.0", 16, "192.168.10.30", 5),
            route("earlier", "10.1.0.0", 16, "192.168.10.20", 2),
        ],
    )

    decision = table.decide(ip("10.1.2.3"), ttl=16)

    assert decision.selected.source_id == "earlier"


def test_static_tie_lower_metric_wins_before_creation_order():
    table = RouterForwardingTable(
        [interface("i0", 0, "192.168.10.1", 24)],
        [
            route("first", "10.1.0.0", 16, "192.168.10.20", 1, metric=5),
            route("second", "10.1.0.0", 16, "192.168.10.30", 2, metric=1),
        ],
    )

    decision = table.decide(ip("10.1.2.3"), ttl=16)

    assert decision.selected.source_id == "second"


def test_connected_tie_uses_stable_interface_identity():
    table = RouterForwardingTable(
        [
            interface("i-late", 2, "10.0.0.2", 24),
            interface("i-early", 1, "10.0.0.1", 24),
        ]
    )

    decision = table.decide(ip("10.0.0.9"), ttl=16)

    assert decision.selected is not None
    assert decision.egress_interface_id == "i-early"


def test_static_next_hop_uses_longest_matching_connected_subnet():
    table = RouterForwardingTable(
        [
            interface("wide", 0, "10.0.0.1", 8),
            interface("narrow", 1, "10.1.0.1", 16),
        ],
        [route("remote", "172.16.0.0", 16, "10.1.2.2", 1)],
    )

    decision = table.decide(ip("172.16.5.5"), ttl=16)

    assert decision.selected.source_id == "remote"
    assert decision.egress_interface_id == "narrow"
    assert decision.next_hop == ip("10.1.2.2")


def test_host_route_slash_32_is_most_specific():
    table = RouterForwardingTable(
        [interface("i0", 0, "192.168.10.1", 24)],
        [
            route("net", "10.1.0.0", 16, "192.168.10.20", 1),
            route("host", "10.1.2.3", 32, "192.168.10.30", 2),
        ],
    )

    assert table.decide(ip("10.1.2.3"), ttl=16).selected.source_id == "host"
    assert table.decide(ip("10.1.2.4"), ttl=16).selected.source_id == "net"


def test_result_is_independent_of_input_order():
    interfaces = [
        interface("i1", 1, "192.168.20.1", 24),
        interface("i0", 0, "192.168.10.1", 24),
    ]
    routes = [
        route("b", "10.0.0.0", 16, "192.168.10.20", 2),
        route("a", "10.0.0.0", 16, "192.168.10.10", 1),
    ]

    forward = RouterForwardingTable(interfaces, routes).decide(ip("10.0.0.1"), ttl=16)
    backward = RouterForwardingTable(reversed(interfaces), reversed(routes)).decide(
        ip("10.0.0.1"), ttl=16
    )

    assert forward == backward
    assert forward.selected.source_id == "a"


def test_duplicate_interface_and_route_identities_are_rejected():
    with pytest.raises(ValueError):
        RouterForwardingTable(
            [interface("i0", 0, "10.0.0.1", 24), interface("i0", 1, "10.0.1.1", 24)]
        )
    with pytest.raises(ValueError):
        RouterForwardingTable(
            [interface("i0", 0, "192.168.10.1", 24)],
            [
                route("a", "10.0.0.0", 16, "192.168.10.20", 1),
                route("a", "10.1.0.0", 16, "192.168.10.20", 2),
            ],
        )
    with pytest.raises(ValueError):
        RouterForwardingTable(
            [interface("i0", 0, "192.168.10.1", 24)],
            [
                route("a", "10.0.0.0", 16, "192.168.10.20", 1),
                route("b", "10.1.0.0", 16, "192.168.10.20", 1),
            ],
        )


def test_interface_and_route_validation():
    with pytest.raises(ValueError):
        RouterInterface("i0", "r1", 0, 1, ip("10.0.0.1"), None)
    with pytest.raises(ValueError):
        RouterInterface("i0", "r1", 0, 1, ip("10.0.0.1"), 31)
    with pytest.raises(ValueError):
        StaticRouteConfig("r", ip("10.0.0.9"), 24, ip("192.168.1.1"), 1)
    with pytest.raises(ValueError):
        StaticRouteConfig("r", ip("10.0.0.0"), 24, ip("224.0.0.1"), 1)
    with pytest.raises(ValueError):
        StaticRouteConfig("r", ip("10.0.0.0"), 24, ip("192.168.1.1"), 0)
    with pytest.raises(InvalidIPv4AddressError):
        RouterInterface("i0", "r1", 0, 1, -1, 24)


def test_inactive_interface_address_is_not_local_delivery():
    table = RouterForwardingTable([interface("i0", 0, "192.168.10.1", 24, admin=False)])

    decision = table.decide(ip("192.168.10.1"), ttl=16)

    assert decision.status is RouteDecisionStatus.NO_ELIGIBLE_ROUTE
    assert not decision.is_local


def test_peer_disabled_connected_route_is_ineligible():
    table = RouterForwardingTable([interface("i0", 0, "192.168.10.1", 24, link=False)])

    decision = table.decide(ip("192.168.10.10"), ttl=16)

    assert decision.status is RouteDecisionStatus.NO_ELIGIBLE_ROUTE


@pytest.mark.parametrize("next_hop", ["192.168.10.0", "192.168.10.255"])
def test_static_next_hop_network_or_broadcast_is_ineligible(next_hop):
    table = RouterForwardingTable(
        [interface("i0", 0, "192.168.10.1", 24)],
        [route("bad", "10.1.0.0", 16, next_hop, 1)],
    )

    decision = table.decide(ip("10.1.2.3"), ttl=16)

    assert decision.status is RouteDecisionStatus.NO_ELIGIBLE_ROUTE
    assert decision.ineligible_candidates[0].source_id == "bad"


def test_topology_route_bridge_parses_dotted_decimals():
    from app.engine.topology.models import StaticRoute

    domain_route = StaticRoute(
        route_id="0190f5c0-0000-7000-8000-000000000001",
        router_device_id="0190f5c0-0000-7000-8000-000000000002",
        destination_network="10.1.0.0",
        prefix_length=16,
        next_hop_ipv4="192.168.10.254",
        route_sequence=3,
    )

    config = StaticRouteConfig.from_topology_route(domain_route)

    assert config.destination == ip("10.1.0.0")
    assert config.next_hop == ip("192.168.10.254")
    assert config.route_sequence == 3
