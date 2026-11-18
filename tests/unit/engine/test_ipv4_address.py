import pytest

from app.engine.ipv4.address import (
    HostAddressProblem,
    InvalidIPv4AddressError,
    InvalidSubnetMaskError,
    broadcast_address,
    format_ipv4,
    host_address_problem,
    is_contiguous_mask,
    network_address,
    parse_ipv4,
    parse_subnet_mask,
    prefix_length,
    same_subnet,
)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("0.0.0.0", 0),
        ("192.168.1.10", 0xC0A8010A),
        ("255.255.255.255", 0xFFFFFFFF),
    ],
)
def test_parse_and_format_roundtrip(text, value):
    assert parse_ipv4(text) == value
    assert format_ipv4(value) == text


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1.2.3",
        "1.2.3.4.5",
        "1.2.3.256",
        "1.2.3.-1",
        "1.2.3.a",
        "1..3.4",
        " 1.2.3.4",
        "1.2.3.4 ",
        "01.2.3.4",
        "+1.2.3.4",
        "1.2.3.\u0664",  # Arabic-Indic digit must not be accepted
        "192.168.1.1/24",
    ],
)
def test_parse_rejects_malformed(bad):
    with pytest.raises(InvalidIPv4AddressError):
        parse_ipv4(bad)


def test_parse_rejects_non_string():
    with pytest.raises(InvalidIPv4AddressError):
        parse_ipv4(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-1, 2**32, 1.5, True, "1"])
def test_format_rejects_non_32_bit_values(bad):
    with pytest.raises(InvalidIPv4AddressError):
        format_ipv4(bad)


@pytest.mark.parametrize(
    ("text", "prefix"),
    [
        ("0.0.0.0", 0),
        ("128.0.0.0", 1),
        ("255.0.0.0", 8),
        ("255.255.255.0", 24),
        ("255.255.255.252", 30),
        ("255.255.255.254", 31),
        ("255.255.255.255", 32),
    ],
)
def test_valid_masks(text, prefix):
    mask = parse_subnet_mask(text)

    assert is_contiguous_mask(mask)
    assert prefix_length(mask) == prefix


@pytest.mark.parametrize("bad", ["255.0.255.0", "255.255.255.1", "0.255.255.255", "1.1.1.1", "x"])
def test_invalid_masks(bad):
    with pytest.raises(InvalidSubnetMaskError):
        parse_subnet_mask(bad)


def test_network_and_broadcast():
    address = parse_ipv4("192.168.1.130")
    mask = parse_subnet_mask("255.255.255.128")

    assert format_ipv4(network_address(address, mask)) == "192.168.1.128"
    assert format_ipv4(broadcast_address(address, mask)) == "192.168.1.255"


def test_same_subnet():
    mask = parse_subnet_mask("255.255.255.0")

    assert same_subnet(parse_ipv4("10.0.0.5"), parse_ipv4("10.0.0.200"), mask)
    assert not same_subnet(parse_ipv4("10.0.0.5"), parse_ipv4("10.0.1.5"), mask)


def test_helpers_reject_non_contiguous_mask():
    with pytest.raises(InvalidSubnetMaskError):
        network_address(parse_ipv4("10.0.0.1"), 0xFF00FF00)


@pytest.mark.parametrize(
    ("address", "mask", "expected"),
    [
        ("192.168.1.10", "255.255.255.0", None),
        ("192.168.1.0", "255.255.255.0", HostAddressProblem.NETWORK_ADDRESS),
        ("192.168.1.255", "255.255.255.0", HostAddressProblem.BROADCAST_ADDRESS),
        ("192.168.1.1", "255.255.255.254", HostAddressProblem.UNSUPPORTED_PREFIX_LENGTH),
        ("192.168.1.1", "255.255.255.255", HostAddressProblem.UNSUPPORTED_PREFIX_LENGTH),
        ("10.0.0.1", "255.255.255.252", None),
        ("10.0.0.3", "255.255.255.252", HostAddressProblem.BROADCAST_ADDRESS),
    ],
)
def test_host_address_problem(address, mask, expected):
    assert host_address_problem(parse_ipv4(address), parse_subnet_mask(mask)) == expected
