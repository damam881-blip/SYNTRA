import pytest

from app.engine.ipv4.address import InvalidIPv4AddressError, InvalidSubnetMaskError
from app.engine.ipv4.address import parse_ipv4 as ip
from app.engine.ipv4.address import parse_subnet_mask as mask
from app.engine.routing.table import DEFAULT_METRIC, RoutingTable, StaticRoute


def route(route_id, destination, subnet_mask, next_hop, metric=DEFAULT_METRIC):
    return StaticRoute(route_id, ip(destination), mask(subnet_mask), ip(next_hop), metric)


def test_default_metric_is_one():
    assert route("r1", "10.0.0.0", "255.0.0.0", "192.168.0.1").metric == 1


def test_longest_prefix_wins_over_metric():
    table = RoutingTable(
        [
            route("a", "10.0.0.0", "255.0.0.0", "192.168.0.1", metric=1),
            route("b", "10.1.0.0", "255.255.0.0", "192.168.0.2", metric=50),
        ]
    )

    best = table.best_route(ip("10.1.2.3"))

    assert best is not None
    assert best.route_id == "b"


def test_equal_prefix_lowest_metric_wins():
    table = RoutingTable(
        [
            route("a", "10.0.0.0", "255.0.0.0", "192.168.0.1", metric=5),
            route("b", "10.0.0.0", "255.0.0.0", "192.168.0.2", metric=2),
        ]
    )

    assert table.best_route(ip("10.9.9.9")).route_id == "b"


def test_equal_prefix_and_metric_lowest_route_id_wins():
    table = RoutingTable(
        [
            route("route-b", "10.0.0.0", "255.0.0.0", "192.168.0.2"),
            route("route-a", "10.0.0.0", "255.0.0.0", "192.168.0.1"),
        ]
    )

    assert table.best_route(ip("10.0.0.1")).route_id == "route-a"


def test_default_route_matches_everything_with_lowest_priority():
    table = RoutingTable(
        [
            route("default", "0.0.0.0", "0.0.0.0", "192.168.0.254"),
            route("lan", "172.16.0.0", "255.255.0.0", "192.168.0.1"),
        ]
    )

    assert table.routes[0].route_id == "default"
    assert table.routes[0].is_default
    assert table.best_route(ip("8.8.8.8")).route_id == "default"
    assert table.best_route(ip("172.16.5.5")).route_id == "lan"


def test_no_match_returns_none_and_empty_ranking():
    table = RoutingTable([route("a", "10.0.0.0", "255.0.0.0", "192.168.0.1")])

    assert table.best_route(ip("11.0.0.1")) is None
    assert table.matching_routes(ip("11.0.0.1")) == ()
    assert RoutingTable().best_route(ip("1.1.1.1")) is None


def test_host_route_slash_32_is_most_specific():
    table = RoutingTable(
        [
            route("net", "10.0.0.0", "255.255.255.0", "192.168.0.1"),
            route("host", "10.0.0.7", "255.255.255.255", "192.168.0.2"),
        ]
    )

    assert table.best_route(ip("10.0.0.7")).route_id == "host"
    assert table.best_route(ip("10.0.0.8")).route_id == "net"


def test_matching_routes_are_ranked_best_first():
    table = RoutingTable(
        [
            route("default", "0.0.0.0", "0.0.0.0", "192.168.0.254"),
            route("wide", "10.0.0.0", "255.0.0.0", "192.168.0.1"),
            route("narrow", "10.1.0.0", "255.255.0.0", "192.168.0.2"),
        ]
    )

    ranked = [r.route_id for r in table.matching_routes(ip("10.1.1.1"))]

    assert ranked == ["narrow", "wide", "default"]


def test_result_does_not_depend_on_input_order():
    routes = [
        route("c", "10.0.0.0", "255.0.0.0", "192.168.0.3"),
        route("a", "10.0.0.0", "255.0.0.0", "192.168.0.1"),
        route("b", "10.0.0.0", "255.0.0.0", "192.168.0.2"),
    ]

    forward = RoutingTable(routes).matching_routes(ip("10.0.0.1"))
    backward = RoutingTable(reversed(routes)).matching_routes(ip("10.0.0.1"))

    assert forward == backward
    assert [r.route_id for r in forward] == ["a", "b", "c"]


def test_stray_host_bits_in_destination_do_not_change_matching():
    table = RoutingTable([route("a", "10.0.0.99", "255.255.255.0", "192.168.0.1")])

    assert table.best_route(ip("10.0.0.5")) is not None
    assert table.best_route(ip("10.0.1.5")) is None


def test_duplicate_route_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        RoutingTable(
            [
                route("a", "10.0.0.0", "255.0.0.0", "192.168.0.1"),
                route("a", "11.0.0.0", "255.0.0.0", "192.168.0.1"),
            ]
        )


def test_invalid_route_fields_are_rejected():
    with pytest.raises(InvalidSubnetMaskError):
        StaticRoute("a", ip("10.0.0.0"), 0xFF00FF00, ip("192.168.0.1"))
    with pytest.raises(InvalidIPv4AddressError):
        StaticRoute("a", -1, mask("255.0.0.0"), ip("192.168.0.1"))
    with pytest.raises(InvalidIPv4AddressError):
        StaticRoute("a", ip("10.0.0.0"), mask("255.0.0.0"), 2**32)
    with pytest.raises(ValueError):
        StaticRoute("", ip("10.0.0.0"), mask("255.0.0.0"), ip("192.168.0.1"))


@pytest.mark.parametrize("bad_metric", [-1, True, 1.5, "1", None])
def test_invalid_metric_is_rejected(bad_metric):
    with pytest.raises(ValueError):
        StaticRoute("a", ip("10.0.0.0"), mask("255.0.0.0"), ip("192.168.0.1"), bad_metric)
