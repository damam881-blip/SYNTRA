"""Pure MAC address primitives: a MAC is a plain 48-bit int inside the engine.

PROPOSED text form: six colon-separated groups of exactly two hex digits
(case-insensitive on input, lowercase on output).
"""

_MAX_MAC = 0xFFFFFFFFFFFF
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

BROADCAST_MAC = _MAX_MAC


class InvalidMacAddressError(ValueError):
    """Malformed MAC address."""


def parse_mac(text: str) -> int:
    if type(text) is not str:
        raise InvalidMacAddressError("MAC address must be a string")

    groups = text.split(":")
    if len(groups) != 6:
        raise InvalidMacAddressError(f"MAC address must have six groups: {text!r}")

    value = 0
    for group in groups:
        if len(group) != 2 or not all(char in _HEX_DIGITS for char in group):
            raise InvalidMacAddressError(f"invalid MAC group {group!r} in {text!r}")
        value = (value << 8) | int(group, 16)

    return value


def format_mac(value: int) -> str:
    _check_mac(value)
    return ":".join(f"{(value >> shift) & 0xFF:02x}" for shift in (40, 32, 24, 16, 8, 0))


def is_broadcast(mac: int) -> bool:
    _check_mac(mac)
    return mac == BROADCAST_MAC


def is_group_address(mac: int) -> bool:
    """True when the I/G bit (least significant bit of the first octet) is set."""
    _check_mac(mac)
    return (mac >> 40) & 1 == 1


def _check_mac(value: int) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_MAC:
        raise InvalidMacAddressError(f"not a 48-bit MAC value: {value!r}")
