"""Layer 2 switch MAC table (T1-03, T3-08). Pure, deterministic, integer-nanosecond time.

Ports are opaque string IDs (interface IDs supplied by the caller).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.engine.ethernet.mac import BROADCAST_MAC, InvalidMacAddressError, is_group_address

MAC_AGING_NS = 300 * 1_000_000_000  # T1-03 / T3-08: 300 s per entry


class LearnOutcome(StrEnum):
    NEW = "NEW"
    REFRESHED = "REFRESHED"
    MOVED = "MOVED"


@dataclass(frozen=True, slots=True)
class LearnResult:
    outcome: LearnOutcome
    previous_port: str | None


class ForwardAction(StrEnum):
    UNICAST = "UNICAST"
    FLOOD = "FLOOD"
    FILTER = "FILTER"


@dataclass(frozen=True, slots=True)
class ForwardDecision:
    action: ForwardAction
    egress_ports: tuple[str, ...]


@dataclass(slots=True)
class _Entry:
    port: str
    learned_at_ns: int


class SwitchMacTable:
    """MAC -> port table. Each entry expires `aging_ns` after its own last learning event.

    PROPOSED: an entry is expired when now_ns >= learned_at_ns + aging_ns.
    """

    def __init__(self, aging_ns: int = MAC_AGING_NS) -> None:
        if type(aging_ns) is not int or aging_ns <= 0:
            raise ValueError("aging_ns must be a positive int")
        self._aging_ns = aging_ns
        self._entries: dict[int, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def learn(self, mac: int, port: str, now_ns: int) -> LearnResult:
        """Learn source MAC -> ingress port; refreshes only this MAC's entry."""
        _check_time(now_ns)
        _check_port(port)
        if is_group_address(mac):
            raise InvalidMacAddressError("group/broadcast address cannot be a source MAC")

        previous = self._live_entry(mac, now_ns)
        self._entries[mac] = _Entry(port=port, learned_at_ns=now_ns)

        if previous is None:
            return LearnResult(LearnOutcome.NEW, None)
        if previous.port == port:
            return LearnResult(LearnOutcome.REFRESHED, port)
        return LearnResult(LearnOutcome.MOVED, previous.port)

    def lookup(self, mac: int, now_ns: int) -> str | None:
        """Learned port for `mac`, or None if unknown or expired (expired entries are purged)."""
        _check_time(now_ns)
        entry = self._live_entry(mac, now_ns)
        return None if entry is None else entry.port

    def decide(
        self,
        *,
        ingress_port: str,
        source_mac: int,
        destination_mac: int,
        eligible_ports: Sequence[str],
        now_ns: int,
    ) -> tuple[LearnResult, ForwardDecision]:
        """Learn the source, then choose egress ports.

        `eligible_ports` must be an ordered sequence (never a set, to keep results
        deterministic); the ingress port is always excluded from egress.
        """
        if isinstance(eligible_ports, set | frozenset | dict | str):
            raise TypeError("eligible_ports must be an ordered sequence of port IDs")

        learn_result = self.learn(source_mac, ingress_port, now_ns)
        flood = ForwardDecision(
            ForwardAction.FLOOD,
            tuple(port for port in eligible_ports if port != ingress_port),
        )

        if destination_mac == BROADCAST_MAC:
            return learn_result, flood

        learned_port = self.lookup(destination_mac, now_ns)
        if learned_port is None:
            return learn_result, flood
        if learned_port == ingress_port:
            # PROPOSED: known destination behind the ingress port is filtered.
            return learn_result, ForwardDecision(ForwardAction.FILTER, ())
        if learned_port in eligible_ports:
            return learn_result, ForwardDecision(ForwardAction.UNICAST, (learned_port,))
        # PROPOSED: learned port not currently eligible -> treat as unknown, flood.
        return learn_result, flood

    def _live_entry(self, mac: int, now_ns: int) -> _Entry | None:
        entry = self._entries.get(mac)
        if entry is None:
            return None
        if now_ns >= entry.learned_at_ns + self._aging_ns:
            del self._entries[mac]
            return None
        return entry


def _check_time(now_ns: int) -> None:
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("now_ns must be a non-negative int")


def _check_port(port: str) -> None:
    if type(port) is not str or not port:
        raise ValueError("port must be a non-empty string")
