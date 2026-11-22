"""Pure TASK-02/TASK-04 validation helpers for project mutation services.

The rules encoded here are structural configuration rules, not simulation
behaviour. They are applied by the TASK-06 service inside the caller's
transaction, before any row is written, so a rejected mutation advances no
revision and commits nothing.
"""

from __future__ import annotations

from typing import Literal

from app.db.enums import CableType, DeviceKind
from app.db.errors import ContractValidationError
from app.engine.ipv4.address import (
    InvalidIPv4AddressError,
    host_address_problem,
    parse_ipv4,
    prefix_mask,
)
from app.engine.ipv4.policy import gateway_problem, next_hop_problem

MdiClass = Literal["MDI", "MDI_X"]

_MDI_X_KINDS = frozenset({DeviceKind.L2_SWITCH})

# TASK-02 NET-03 / TASK-04 MDI matrix. GENERIC_ETHERNET models Auto-MDIX and
# is compatible with every pairing.
_CABLE_MATRIX: dict[tuple[MdiClass, MdiClass], frozenset[CableType]] = {
    ("MDI", "MDI"): frozenset({CableType.GENERIC_ETHERNET, CableType.CROSSOVER}),
    ("MDI", "MDI_X"): frozenset({CableType.GENERIC_ETHERNET, CableType.STRAIGHT_THROUGH}),
    ("MDI_X", "MDI_X"): frozenset({CableType.GENERIC_ETHERNET, CableType.CROSSOVER}),
}


def mdi_class(kind: DeviceKind | str) -> MdiClass:
    """Return the physical MDI class derived from a device kind (TASK-04)."""
    normalized = DeviceKind(kind)
    return "MDI_X" if normalized in _MDI_X_KINDS else "MDI"


def cable_type_allowed(
    first_kind: DeviceKind | str,
    second_kind: DeviceKind | str,
    cable_type: CableType | str,
) -> bool:
    """Whether a cable is allowed for the two endpoint device kinds."""
    pair = tuple(sorted((mdi_class(first_kind), mdi_class(second_kind))))
    return CableType(cable_type) in _CABLE_MATRIX[pair]  # type: ignore[index]


def _parse(address: str, field: str) -> int:
    try:
        return parse_ipv4(address)
    except InvalidIPv4AddressError as error:
        raise ContractValidationError(f"{field} is not a valid IPv4 address: {error}") from error


def validate_host_address(address: str, prefix_length: int) -> None:
    """Reject special-use, network and directed-broadcast host addresses.

    TASK-02 §3.1A: host interface prefixes are /1../30, but structural
    exclusion of 0/8, 127/8, 169.254/16, 224/4, 240/4, limited broadcast,
    network and directed broadcast addresses is independent of the prefix.
    All other structurally valid unicast addresses are allowed.
    """
    value = _parse(address, "address")
    problem = host_address_problem(value, prefix_mask(prefix_length))
    if problem is not None:
        raise ContractValidationError(f"address is not usable as a host address: {problem.value}")


def validate_special_address(
    address: str, field: str, *, role: Literal["gateway", "next_hop"]
) -> None:
    """Reject special-use addresses for a gateway or static-route next hop.

    Route *destination* networks are not host addresses and are validated
    separately (0.0.0.0/0 remains a valid default route destination).
    ``gateway_problem(..., None, None)`` defers on-link/self-reference checks to
    TASK-03, so off-link and self-referencing gateways remain storable.
    """
    value = _parse(address, field)
    problem = gateway_problem(value, None, None) if role == "gateway" else next_hop_problem(value)
    if problem is not None:
        raise ContractValidationError(f"{field} is not a valid unicast address: {problem.value}")
