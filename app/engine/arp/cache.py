"""Per-device ARP cache: IPv4 -> MAC (T3-07). Pure, deterministic, integer-nanosecond time.

Every PC, Server and Router owns its own ARP cache instance. This is NOT the switch
MAC table (MAC -> port). A fresh test starts with an empty cache (initial_runtime_state FRESH).

Who updates the cache, and on which ARP events, is decided by the ARP resolution logic,
not here.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.engine.ethernet.mac import is_group_address
from app.engine.ipv4.address import InvalidIPv4AddressError

ARP_CACHE_LIFETIME_NS = 60 * 1_000_000_000  # T3-07: 60 s
_MAX_ADDRESS = 0xFFFFFFFF


class ArpUpdateOutcome(StrEnum):
    NEW = "NEW"
    REFRESHED = "REFRESHED"
    CHANGED = "CHANGED"


@dataclass(frozen=True, slots=True)
class ArpUpdateResult:
    outcome: ArpUpdateOutcome
    previous_mac: int | None


@dataclass(slots=True)
class _Entry:
    mac: int
    updated_at_ns: int


class ArpCache:
    """IP -> MAC cache. Each entry lives `lifetime_ns` from its own last update.

    PROPOSED: lifetime is counted from the last update (not extended by lookups), and an
    entry is expired when now_ns >= updated_at_ns + lifetime_ns (same boundary as the
    switch MAC table).
    """

    def __init__(self, lifetime_ns: int = ARP_CACHE_LIFETIME_NS) -> None:
        if type(lifetime_ns) is not int or lifetime_ns <= 0:
            raise ValueError("lifetime_ns must be a positive int")
        self._lifetime_ns = lifetime_ns
        self._entries: dict[int, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def update(self, ip: int, mac: int, now_ns: int) -> ArpUpdateResult:
        _check_time(now_ns)
        _check_ip(ip)
        if is_group_address(mac):
            raise ValueError("ARP cache cannot map an IP to a group/broadcast MAC")

        previous = self._live_entry(ip, now_ns)
        self._entries[ip] = _Entry(mac=mac, updated_at_ns=now_ns)

        if previous is None:
            return ArpUpdateResult(ArpUpdateOutcome.NEW, None)
        if previous.mac == mac:
            return ArpUpdateResult(ArpUpdateOutcome.REFRESHED, mac)
        return ArpUpdateResult(ArpUpdateOutcome.CHANGED, previous.mac)

    def lookup(self, ip: int, now_ns: int) -> int | None:
        """MAC for `ip`, or None if unknown or expired (expired entries are purged)."""
        _check_time(now_ns)
        _check_ip(ip)
        entry = self._live_entry(ip, now_ns)
        return None if entry is None else entry.mac

    def _live_entry(self, ip: int, now_ns: int) -> _Entry | None:
        entry = self._entries.get(ip)
        if entry is None:
            return None
        if now_ns >= entry.updated_at_ns + self._lifetime_ns:
            del self._entries[ip]
            return None
        return entry


def _check_time(now_ns: int) -> None:
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("now_ns must be a non-negative int")


def _check_ip(ip: int) -> None:
    if type(ip) is not int or not 0 <= ip <= _MAX_ADDRESS:
        raise InvalidIPv4AddressError(f"not a 32-bit IPv4 value: {ip!r}")
