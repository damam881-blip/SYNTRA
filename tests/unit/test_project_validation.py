"""Structural MDI/cable and IPv4 validation applied by the TASK-06 service."""

import pytest

from app.db.enums import CableType, DeviceKind
from app.db.errors import ContractValidationError
from app.modules.projects.validation import (
    cable_type_allowed,
    mdi_class,
    validate_host_address,
    validate_special_address,
)

# TASK-02 NET-03 / TASK-04 reference matrix, stated independently of the code.
_ALLOWED = {
    ("MDI", "MDI"): {"GENERIC_ETHERNET", "CROSSOVER"},
    ("MDI", "MDI_X"): {"GENERIC_ETHERNET", "STRAIGHT_THROUGH"},
    ("MDI_X", "MDI_X"): {"GENERIC_ETHERNET", "CROSSOVER"},
}


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (DeviceKind.PC, "MDI"),
        (DeviceKind.SERVER, "MDI"),
        (DeviceKind.ROUTER, "MDI"),
        (DeviceKind.L2_SWITCH, "MDI_X"),
    ],
)
def test_mdi_class(kind, expected):
    assert mdi_class(kind) == expected


@pytest.mark.parametrize("first", list(DeviceKind))
@pytest.mark.parametrize("second", list(DeviceKind))
@pytest.mark.parametrize("cable", list(CableType))
def test_cable_matrix_matches_reference(first, second, cable):
    pair = tuple(sorted((mdi_class(first), mdi_class(second))))
    assert cable_type_allowed(first, second, cable) == (cable.value in _ALLOWED[pair])


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.1",
        "127.0.0.1",
        "169.254.10.1",
        "224.0.0.1",
        "239.255.255.255",
        "240.0.0.1",
        "255.255.255.255",
    ],
)
def test_host_address_rejects_special_ranges(address):
    with pytest.raises(ContractValidationError):
        validate_host_address(address, 24)


@pytest.mark.parametrize("address", ["192.168.1.0", "192.168.1.255"])
def test_host_address_rejects_network_and_broadcast(address):
    with pytest.raises(ContractValidationError):
        validate_host_address(address, 24)


@pytest.mark.parametrize(
    ("address", "prefix"),
    [
        ("192.168.1.10", 24),
        ("10.0.0.1", 8),
        ("100.64.0.1", 10),
        ("192.0.2.5", 24),
        ("8.8.8.8", 24),
    ],
)
def test_host_address_default_allow(address, prefix):
    validate_host_address(address, prefix)


def test_host_address_rejects_non_ascii_digits():
    with pytest.raises(ContractValidationError):
        validate_host_address("١٩٢.١٦٨.١.١٠", 24)


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.1.1", "224.0.0.1", "255.255.255.255"])
def test_gateway_rejects_special_addresses(address):
    with pytest.raises(ContractValidationError):
        validate_special_address(address, "gateway_ipv4", role="gateway")


def test_gateway_defers_off_link_and_self_reference():
    validate_special_address("192.168.1.1", "gateway_ipv4", role="gateway")
    validate_special_address("8.8.8.8", "gateway_ipv4", role="gateway")


@pytest.mark.parametrize(
    "address", ["0.0.0.0", "127.0.0.1", "169.254.1.1", "224.0.0.1", "240.0.0.1"]
)
def test_next_hop_rejects_special_addresses(address):
    with pytest.raises(ContractValidationError):
        validate_special_address(address, "next_hop_ipv4", role="next_hop")


def test_next_hop_allows_structurally_valid_unicast():
    validate_special_address("192.168.10.2", "next_hop_ipv4", role="next_hop")
