"""Pure IPv4 primitives: addresses and masks are plain 32-bit ints inside the engine.

Strings (dotted-decimal only, T1-01) exist only at the parse/format boundary.
"""

from enum import StrEnum

_MAX_ADDRESS = 0xFFFFFFFF
LIMITED_BROADCAST = _MAX_ADDRESS

# TASK-02 §3.1A: excluded structural ranges for host/gateway/next-hop addresses.
EXCLUDED_IPV4_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x00000000, 8, "0.0.0.0/8"),
    (0x7F000000, 8, "127.0.0.0/8"),
    (0xA9FE0000, 16, "169.254.0.0/16"),
    (0xE0000000, 4, "224.0.0.0/4"),
    (0xF0000000, 4, "240.0.0.0/4"),
)

MIN_HOST_PREFIX_LENGTH = 1
MAX_HOST_PREFIX_LENGTH = 30


class InvalidIPv4AddressError(ValueError):
    """Malformed IPv4 address (T2-02)."""


class InvalidSubnetMaskError(ValueError):
    """Malformed or non-contiguous subnet mask (T2-02)."""


class HostAddressProblem(StrEnum):
    """Structural reasons an address cannot be used as an interface/host address.

    These are input/configuration errors (T2-05), not simulation diagnostics.
    """

    UNSUPPORTED_PREFIX_LENGTH = "UNSUPPORTED_PREFIX_LENGTH"
    NETWORK_ADDRESS = "NETWORK_ADDRESS"
    BROADCAST_ADDRESS = "BROADCAST_ADDRESS"
    EXCLUDED_ADDRESS = "EXCLUDED_ADDRESS"
    LIMITED_BROADCAST = "LIMITED_BROADCAST"


def parse_ipv4(text: str) -> int:
    """Parse strict dotted-decimal: four ASCII-decimal octets, each 0-255.

    PROPOSED: leading zeros ("01") are rejected to avoid octal ambiguity.
    """
    if type(text) is not str:
        raise InvalidIPv4AddressError("IPv4 address must be a string")

    parts = text.split(".")
    if len(parts) != 4:
        raise InvalidIPv4AddressError(f"IPv4 address must have four octets: {text!r}")

    value = 0
    for part in parts:
        if not (part.isascii() and part.isdigit()):
            raise InvalidIPv4AddressError(f"invalid octet {part!r} in {text!r}")
        if len(part) > 1 and part.startswith("0"):
            raise InvalidIPv4AddressError(f"leading zeros are not allowed: {text!r}")
        octet = int(part)
        if octet > 255:
            raise InvalidIPv4AddressError(f"octet out of range 0-255: {text!r}")
        value = (value << 8) | octet

    return value


def format_ipv4(value: int) -> str:
    _check_address(value)
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def is_contiguous_mask(mask: int) -> bool:
    """True when the mask is 1-bits followed by 0-bits (0.0.0.0 and /32 included)."""
    if type(mask) is not int or not 0 <= mask <= _MAX_ADDRESS:
        return False
    inverted = ~mask & _MAX_ADDRESS
    return inverted & (inverted + 1) == 0


def parse_subnet_mask(text: str) -> int:
    try:
        mask = parse_ipv4(text)
    except InvalidIPv4AddressError as error:
        raise InvalidSubnetMaskError(str(error)) from error

    if not is_contiguous_mask(mask):
        raise InvalidSubnetMaskError(f"subnet mask is not contiguous: {text!r}")
    return mask


def prefix_length(mask: int) -> int:
    _check_mask(mask)
    return 32 - (~mask & _MAX_ADDRESS).bit_length()


def network_address(address: int, mask: int) -> int:
    _check_address(address)
    _check_mask(mask)
    return address & mask


def broadcast_address(address: int, mask: int) -> int:
    _check_address(address)
    _check_mask(mask)
    return address | (~mask & _MAX_ADDRESS)


def same_subnet(first: int, second: int, mask: int) -> bool:
    """True when both addresses share a network under the given mask."""
    return network_address(first, mask) == network_address(second, mask)


def prefix_mask(prefix: int) -> int:
    """Return the contiguous mask for a prefix length 0..32."""
    if type(prefix) is not int or not 0 <= prefix <= 32:
        raise ValueError("prefix length must be an int between 0 and 32")
    if prefix == 0:
        return 0
    return (0xFFFFFFFF << (32 - prefix)) & _MAX_ADDRESS


def special_address_problem(address: int) -> HostAddressProblem | None:
    """Classify an address that is structurally unusable as a host/next-hop address.

    TASK-02 §3.1A excludes 0.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 224.0.0.0/4
    and 240.0.0.0/4. The limited broadcast address is reported separately.
    """
    _check_address(address)
    if address == LIMITED_BROADCAST:
        return HostAddressProblem.LIMITED_BROADCAST
    for network, prefix, _name in EXCLUDED_IPV4_RANGES:
        if address & prefix_mask(prefix) == network:
            return HostAddressProblem.EXCLUDED_ADDRESS
    return None


def host_address_problem(address: int, mask: int) -> HostAddressProblem | None:
    """Return why `address/mask` is unusable as a host address, or None if usable.

    Host interface prefixes are /1../30 in V1; route masks may still be /0../32.
    """
    special = special_address_problem(address)
    if special is not None:
        return special
    prefix = prefix_length(mask)
    if not MIN_HOST_PREFIX_LENGTH <= prefix <= MAX_HOST_PREFIX_LENGTH:
        return HostAddressProblem.UNSUPPORTED_PREFIX_LENGTH
    if address == network_address(address, mask):
        return HostAddressProblem.NETWORK_ADDRESS
    if address == broadcast_address(address, mask):
        return HostAddressProblem.BROADCAST_ADDRESS
    return None


def _check_address(value: int) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_ADDRESS:
        raise InvalidIPv4AddressError(f"not a 32-bit IPv4 value: {value!r}")


def _check_mask(mask: int) -> None:
    if not is_contiguous_mask(mask):
        raise InvalidSubnetMaskError(f"not a contiguous 32-bit mask: {mask!r}")
