"""Shared SQLAlchemy foundation for the TASK-06 persistence layer."""

from __future__ import annotations

import ipaddress
import secrets
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, Enum, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid7() -> uuid.UUID:
    """Return a canonical UUIDv7 (48-bit Unix ms + version 7 + RFC 4122 variant)."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return uuid.UUID(int=value)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ipv4_to_int(address: str) -> int:
    """Canonical dotted-decimal IPv4 to uint32; rejects leading zeros."""
    if not isinstance(address, str):
        raise TypeError("IPv4 address must be a string")
    parts = address.split(".")
    if len(parts) != 4 or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid IPv4 address: {address!r}")
    if any(len(part) > 1 and part.startswith("0") for part in parts):
        raise ValueError(f"IPv4 address must not contain leading zeros: {address!r}")
    octets = [int(part) for part in parts]
    if any(octet < 0 or octet > 255 for octet in octets):
        raise ValueError(f"invalid IPv4 address: {address!r}")
    return (
        (octets[0] << 24)
        | (octets[1] << 16)
        | (octets[2] << 8)
        | octets[3]
    )


def int_to_ipv4(value: int) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("IPv4 value must be an int")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("IPv4 value must be between 0 and 4294967295")
    return str(ipaddress.IPv4Address(value))


class IPv4UInt32(TypeDecorator[int]):
    """TASK-04 T4-DEC-02: store IPv4 as uint32, never as text."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, str):
            return ipv4_to_int(value)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("IPv4 values must be int or canonical dotted-decimal str")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("IPv4 values must be between 0 and 4294967295")
        return value

    def process_result_value(self, value: object, dialect: object) -> int | None:
        if value is None:
            return None
        return int(value)  # type: ignore[arg-type]


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """PostgreSQL enum that stores the approved wire spelling (value, not name)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def uuid7_check(column: str, name: str) -> CheckConstraint:
    return CheckConstraint(
        f"substring({column}::text, 15, 1) = '7' "
        f"AND substring({column}::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name=name,
    )


def non_negative_check(column: str, name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} >= 0", name=name)


def positive_check(column: str, name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} >= 1", name=name)
