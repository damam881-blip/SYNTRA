"""Static routing table (T3-01, T3-02). Pure and deterministic.

Fields per route: Destination Network, Subnet Mask, Next Hop (no Exit Interface in V1).
Selection order: Longest Prefix Match -> lowest Metric -> lowest Route ID.

Next-hop usability (T3-03) is NOT decided here: it needs interface data and belongs to the
Ping/forwarding stage. This module only ranks matching routes.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.engine.ipv4.address import (
    InvalidIPv4AddressError,
    InvalidSubnetMaskError,
    is_contiguous_mask,
    prefix_length,
)

DEFAULT_METRIC = 1  # T3-02
_MAX_ADDRESS = 0xFFFFFFFF


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_ADDRESS:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")


@dataclass(frozen=True, slots=True)
class StaticRoute:
    route_id: str
    destination: int
    mask: int
    next_hop: int
    metric: int = DEFAULT_METRIC

    def __post_init__(self) -> None:
        if type(self.route_id) is not str or not self.route_id:
            raise ValueError("route_id must be a non-empty string")
        _check_address("destination", self.destination)
        _check_address("next_hop", self.next_hop)
        if not is_contiguous_mask(self.mask):
            raise InvalidSubnetMaskError(f"route mask is not contiguous: {self.mask!r}")
        # bool is an int subclass; reject it explicitly.
        if type(self.metric) is not int or self.metric < 0:
            raise ValueError("metric must be a non-negative int")

    @property
    def prefix_length(self) -> int:
        return prefix_length(self.mask)

    @property
    def is_default(self) -> bool:
        """Default route is 0.0.0.0 / 0.0.0.0 (T3-01)."""
        return self.destination == 0 and self.mask == 0

    def matches(self, address: int) -> bool:
        """Match by masking both sides, so stray host bits in `destination` never matter."""
        _check_address("address", address)
        return address & self.mask == self.destination & self.mask


def _rank_key(route: StaticRoute) -> tuple[int, int, str]:
    return (-route.prefix_length, route.metric, route.route_id)


class RoutingTable:
    """Immutable collection of routes; results never depend on the input order."""

    def __init__(self, routes: Iterable[StaticRoute] = ()) -> None:
        ordered = sorted(routes, key=lambda route: route.route_id)
        ids = [route.route_id for route in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate route_id in routing table")
        self._routes: tuple[StaticRoute, ...] = tuple(ordered)

    @property
    def routes(self) -> tuple[StaticRoute, ...]:
        return self._routes

    def __len__(self) -> int:
        return len(self._routes)

    def matching_routes(self, address: int) -> tuple[StaticRoute, ...]:
        """All routes matching `address`, best first (prefix desc, metric asc, route_id asc)."""
        _check_address("address", address)
        matches = [route for route in self._routes if route.matches(address)]
        return tuple(sorted(matches, key=_rank_key))

    def best_route(self, address: int) -> StaticRoute | None:
        """Highest-ranked matching route, or None (no usability check, see module docstring)."""
        matches = self.matching_routes(address)
        return matches[0] if matches else None
