"""Router forwarding decision pipeline (TASK-03 §4.1, §4.1A, T3-DEC-01..12).

Ranking is deterministic: longest prefix, then metric, then connected over static,
then immutable route creation order for static routes and stable interface identity
for connected routes. Ineligible candidates are filtered before ranking.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.ipv4.address import (
    InvalidIPv4AddressError,
    host_address_problem,
    network_address,
    prefix_mask,
)
from app.engine.ipv4.policy import next_hop_problem, route_destination_problem

DEFAULT_METRIC = 1


class RouteKind(StrEnum):
    CONNECTED = "CONNECTED"
    STATIC = "STATIC"


class RouteDecisionStatus(StrEnum):
    LOCAL_DELIVERY = "LOCAL_DELIVERY"
    FORWARD = "FORWARD"
    TTL_EXPIRED = "TTL_EXPIRED"
    NO_MATCHING_ROUTE = "NO_MATCHING_ROUTE"
    NO_ELIGIBLE_ROUTE = "NO_ELIGIBLE_ROUTE"


@dataclass(frozen=True, slots=True)
class RouterInterface:
    """The routing-relevant view of one router interface."""

    interface_id: str
    device_id: str
    ordinal: int
    device_sequence: int
    address: int | None = None
    prefix_length: int | None = None
    admin_enabled: bool = True
    link_operational: bool = True

    def __post_init__(self) -> None:
        for field_name in ("interface_id", "device_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if type(self.ordinal) is not int or not 0 <= self.ordinal <= 7:
            raise ValueError("ordinal must be an int between 0 and 7")
        if type(self.device_sequence) is not int or self.device_sequence < 1:
            raise ValueError("device_sequence must be a positive int")
        if (self.address is None) != (self.prefix_length is None):
            raise ValueError("address and prefix_length must be configured or cleared together")
        if self.address is not None:
            _check_address("address", self.address)
        if self.prefix_length is not None and (
            type(self.prefix_length) is not int or not 1 <= self.prefix_length <= 30
        ):
            raise ValueError("prefix_length must be an int between 1 and 30")
        if not isinstance(self.admin_enabled, bool) or not isinstance(self.link_operational, bool):
            raise TypeError("admin_enabled and link_operational must be bools")

    @property
    def mask(self) -> int | None:
        return None if self.prefix_length is None else prefix_mask(self.prefix_length)

    @property
    def configured(self) -> bool:
        return self.address is not None

    @property
    def operational(self) -> bool:
        return self.admin_enabled and self.link_operational

    @property
    def active(self) -> bool:
        """A connected route is active only with a valid address and operational link."""
        if not self.configured or not self.operational:
            return False
        assert self.address is not None and self.prefix_length is not None
        return host_address_problem(self.address, prefix_mask(self.prefix_length)) is None

    @property
    def identity(self) -> tuple[int, int, str]:
        return (self.device_sequence, self.ordinal, self.interface_id)


@dataclass(frozen=True, slots=True)
class StaticRouteConfig:
    """Integer form of one persisted static route."""

    route_id: str
    destination: int
    prefix_length: int
    next_hop: int
    route_sequence: int
    metric: int = DEFAULT_METRIC

    def __post_init__(self) -> None:
        if not isinstance(self.route_id, str) or not self.route_id:
            raise ValueError("route_id must be a non-empty string")
        _check_address("destination", self.destination)
        _check_address("next_hop", self.next_hop)
        if type(self.prefix_length) is not int or not 0 <= self.prefix_length <= 32:
            raise ValueError("prefix_length must be an int between 0 and 32")
        problem = route_destination_problem(self.destination, self.prefix_length)
        if problem is not None:
            raise ValueError(f"invalid route destination: {problem}")
        if next_hop_problem(self.next_hop) is not None:
            raise ValueError("static next hop is a special-use address")
        if type(self.route_sequence) is not int or self.route_sequence < 1:
            raise ValueError("route_sequence must be a positive int")
        if type(self.metric) is not int or self.metric < 0:
            raise ValueError("metric must be a non-negative int")

    @property
    def mask(self) -> int:
        return prefix_mask(self.prefix_length)

    @classmethod
    def from_topology_route(cls, route: object) -> StaticRouteConfig:
        """Bridge from the TASK-04 domain route (dotted-decimal strings)."""
        from app.engine.ipv4.address import parse_ipv4

        return cls(
            route_id=route.route_id,  # type: ignore[attr-defined]
            destination=parse_ipv4(route.destination_network),  # type: ignore[attr-defined]
            prefix_length=route.prefix_length,  # type: ignore[attr-defined]
            next_hop=parse_ipv4(route.next_hop_ipv4),  # type: ignore[attr-defined]
            route_sequence=route.route_sequence,  # type: ignore[attr-defined]
        )


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    kind: RouteKind
    destination: int
    prefix_length: int
    metric: int
    next_hop: int
    egress_interface_id: str
    eligible: bool = True
    ineligible_reason: DiagnosticCode | None = None
    route_sequence: int | None = None
    interface_identity: tuple[int, int, str] | None = None
    source_id: str = ""

    @property
    def mask(self) -> int:
        return prefix_mask(self.prefix_length)

    @property
    def network(self) -> int:
        return network_address(self.destination, self.mask)

    def matches(self, address: int) -> bool:
        return address & self.mask == self.network

    @property
    def rank_key(self) -> tuple[int, int, int, tuple[int, int, str]]:
        if self.kind is RouteKind.CONNECTED:
            assert self.interface_identity is not None
            tiebreak = self.interface_identity
            kind_rank = 0
        else:
            assert self.route_sequence is not None
            tiebreak = (self.route_sequence, 0, self.source_id)
            kind_rank = 1
        return (-self.prefix_length, self.metric, kind_rank, tiebreak)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    status: RouteDecisionStatus
    destination: int
    selected: RouteCandidate | None = None
    matched_candidates: tuple[RouteCandidate, ...] = ()
    eligible_candidates: tuple[RouteCandidate, ...] = ()
    ineligible_candidates: tuple[RouteCandidate, ...] = ()

    @property
    def is_forwarded(self) -> bool:
        return self.status == RouteDecisionStatus.FORWARD

    @property
    def is_local(self) -> bool:
        return self.status == RouteDecisionStatus.LOCAL_DELIVERY

    @property
    def next_hop(self) -> int | None:
        if self.selected is None:
            return None
        if self.selected.kind is RouteKind.CONNECTED:
            return self.destination
        return self.selected.next_hop

    @property
    def egress_interface_id(self) -> str | None:
        return None if self.selected is None else self.selected.egress_interface_id

    @property
    def diagnostic_code(self) -> DiagnosticCode | None:
        if self.status == RouteDecisionStatus.TTL_EXPIRED:
            return DiagnosticCode.TTL_EXPIRED
        if self.status == RouteDecisionStatus.NO_MATCHING_ROUTE:
            return DiagnosticCode.NO_MATCHING_ROUTE
        if self.status == RouteDecisionStatus.NO_ELIGIBLE_ROUTE:
            return DiagnosticCode.NO_ELIGIBLE_ROUTE
        return None


class RouterForwardingTable:
    """Immutable routing view for one router in one simulation snapshot."""

    def __init__(
        self,
        interfaces: Iterable[RouterInterface],
        static_routes: Iterable[StaticRouteConfig] = (),
    ) -> None:
        ordered_interfaces = tuple(sorted(interfaces, key=lambda interface: interface.identity))
        interface_ids = [interface.interface_id for interface in ordered_interfaces]
        if len(set(interface_ids)) != len(interface_ids):
            raise ValueError("duplicate interface_id in router view")

        ordered_routes = tuple(sorted(static_routes, key=lambda route: route.route_sequence))
        route_ids = [route.route_id for route in ordered_routes]
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("duplicate route_id in router view")
        sequences = [route.route_sequence for route in ordered_routes]
        if len(set(sequences)) != len(sequences):
            raise ValueError("duplicate route_sequence in router view")

        self._interfaces = ordered_interfaces
        self._routes = ordered_routes
        self._connected_candidates = tuple(
            self._connected_candidate(interface)
            for interface in ordered_interfaces
            if interface.configured
        )
        self._static_candidates = tuple(self._static_candidate(route) for route in ordered_routes)

    @property
    def interfaces(self) -> tuple[RouterInterface, ...]:
        return self._interfaces

    @property
    def static_routes(self) -> tuple[StaticRouteConfig, ...]:
        return self._routes

    @property
    def local_addresses(self) -> tuple[int, ...]:
        return tuple(
            interface.address
            for interface in self._interfaces
            if interface.active and interface.address is not None
        )

    def decide(
        self,
        destination: int,
        *,
        ttl: int,
        ingress_interface_id: str | None = None,
    ) -> RouteDecision:
        _check_address("destination", destination)
        if type(ttl) is not int or not 0 <= ttl <= 255:
            raise ValueError("ttl must be an int between 0 and 255")
        if ingress_interface_id is not None and ingress_interface_id not in {
            interface.interface_id for interface in self._interfaces
        }:
            raise ValueError(f"unknown ingress interface: {ingress_interface_id!r}")

        if destination in self.local_addresses:
            return RouteDecision(RouteDecisionStatus.LOCAL_DELIVERY, destination)
        if ttl <= 1:
            return RouteDecision(RouteDecisionStatus.TTL_EXPIRED, destination)

        matched = tuple(
            candidate
            for candidate in (*self._connected_candidates, *self._static_candidates)
            if candidate.matches(destination)
        )
        if not matched:
            return RouteDecision(RouteDecisionStatus.NO_MATCHING_ROUTE, destination)

        eligible = tuple(candidate for candidate in matched if candidate.eligible)
        ineligible = tuple(candidate for candidate in matched if not candidate.eligible)
        if not eligible:
            return RouteDecision(
                RouteDecisionStatus.NO_ELIGIBLE_ROUTE,
                destination,
                matched_candidates=matched,
                ineligible_candidates=ineligible,
            )

        ranked = tuple(sorted(eligible, key=lambda candidate: candidate.rank_key))
        return RouteDecision(
            RouteDecisionStatus.FORWARD,
            destination,
            selected=ranked[0],
            matched_candidates=matched,
            eligible_candidates=ranked,
            ineligible_candidates=ineligible,
        )

    def _connected_candidate(self, interface: RouterInterface) -> RouteCandidate:
        assert interface.address is not None and interface.prefix_length is not None
        eligible = interface.active
        mask = prefix_mask(interface.prefix_length)
        return RouteCandidate(
            kind=RouteKind.CONNECTED,
            destination=network_address(interface.address, mask),
            prefix_length=interface.prefix_length,
            metric=DEFAULT_METRIC,
            next_hop=interface.address,
            egress_interface_id=interface.interface_id,
            eligible=eligible,
            ineligible_reason=None if eligible else DiagnosticCode.NO_ELIGIBLE_ROUTE,
            interface_identity=interface.identity,
            source_id=interface.interface_id,
        )

    def _static_candidate(self, route: StaticRouteConfig) -> RouteCandidate:
        egress = self._active_connected_interface_for(route.next_hop)
        reason: DiagnosticCode | None = None

        if any(interface.address == route.next_hop for interface in self._interfaces):
            reason = DiagnosticCode.STATIC_NEXT_HOP_INELIGIBLE
        elif egress is None:
            reason = DiagnosticCode.STATIC_NEXT_HOP_INELIGIBLE
        else:
            assert egress.prefix_length is not None
            if host_address_problem(route.next_hop, prefix_mask(egress.prefix_length)) is not None:
                reason = DiagnosticCode.STATIC_NEXT_HOP_INELIGIBLE

        return RouteCandidate(
            kind=RouteKind.STATIC,
            destination=network_address(route.destination, route.mask),
            prefix_length=route.prefix_length,
            metric=route.metric,
            next_hop=route.next_hop,
            egress_interface_id="" if egress is None else egress.interface_id,
            eligible=reason is None,
            ineligible_reason=reason,
            route_sequence=route.route_sequence,
            source_id=route.route_id,
        )

    def _active_connected_interface_for(self, next_hop: int) -> RouterInterface | None:
        """Longest active connected subnet containing the next hop, then interface identity."""
        reachable = [
            interface
            for interface in self._interfaces
            if interface.active
            and interface.address is not None
            and interface.prefix_length is not None
            and next_hop & prefix_mask(interface.prefix_length)
            == network_address(interface.address, prefix_mask(interface.prefix_length))
        ]
        if not reachable:
            return None
        return min(reachable, key=lambda interface: (-interface.prefix_length, interface.identity))


def connected_prefix_length(interface: RouterInterface) -> int:
    if interface.prefix_length is None:
        raise ValueError("interface has no configured prefix")
    return interface.prefix_length


def _check_address(name: str, value: int) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise InvalidIPv4AddressError(f"{name} is not a 32-bit IPv4 value: {value!r}")
