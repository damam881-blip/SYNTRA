"""Layer 2 switch MAC table (T1-03, T3-08). Pure, deterministic, integer-nanosecond time.

Ports are opaque string IDs (interface IDs supplied by the caller).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.engine.ethernet.mac import BROADCAST_MAC, InvalidMacAddressError, is_group_address

MAC_AGING_NS = 300 * 1_000_000_000  # T1-03 / T3-08: 300 s per entry
MAC_FLAP_WINDOW_NS = 1_000_000_000  # T3-DEC-49: 1000 virtual ms
MAC_FLAP_MOVEMENTS = 3


class LearnOutcome(StrEnum):
    NEW = "NEW"
    REFRESHED = "REFRESHED"
    MOVED = "MOVED"


@dataclass(frozen=True, slots=True)
class LearnResult:
    outcome: LearnOutcome
    previous_port: str | None


@dataclass(frozen=True, slots=True)
class MacFlapEvent:
    """Deterministic MAC-flapping evidence for one (switch, MAC) pair."""

    switch_id: str
    mac: int
    movements: int
    first_moved_at_ns: int
    detected_at_ns: int
    ports: tuple[str, ...]


class MacFlapDetector:
    """Three source-port movements within 1000 ms per (switch, MAC) trigger a flap.

    This detector is intentionally separate from ``SwitchMacTable``: a movement is
    still recorded in the forwarding table even when it produces flap evidence.
    """

    def __init__(
        self,
        *,
        window_ns: int = MAC_FLAP_WINDOW_NS,
        threshold: int = MAC_FLAP_MOVEMENTS,
    ) -> None:
        if type(window_ns) is not int or window_ns <= 0:
            raise ValueError("window_ns must be a positive int")
        if type(threshold) is not int or threshold < 2:
            raise ValueError("threshold must be an int of at least 2")
        self._window_ns = window_ns
        self._threshold = threshold
        self._history: dict[tuple[str, int], list[tuple[int, str, str]]] = {}
        self._flapping: set[tuple[str, int]] = set()

    def record_movement(
        self,
        *,
        switch_id: str,
        mac: int,
        previous_port: str,
        new_port: str,
        now_ns: int,
    ) -> MacFlapEvent | None:
        if not isinstance(switch_id, str) or not switch_id:
            raise ValueError("switch_id must be a non-empty string")
        if is_group_address(mac):
            raise InvalidMacAddressError("group/broadcast MAC cannot flap as a source")
        if previous_port == new_port:
            raise ValueError("a movement requires a different previous and new port")
        _check_port(previous_port)
        _check_port(new_port)
        _check_time(now_ns)

        key = (switch_id, mac)
        history = self._history.setdefault(key, [])
        history.append((now_ns, previous_port, new_port))
        cutoff = now_ns - self._window_ns
        history[:] = [entry for entry in history if entry[0] >= cutoff]

        if len(history) < self._threshold:
            self._flapping.discard(key)
            return None
        if key in self._flapping:
            return None

        self._flapping.add(key)
        ports: list[str] = [history[0][1]]
        ports.extend(entry[2] for entry in history)
        return MacFlapEvent(
            switch_id=switch_id,
            mac=mac,
            movements=len(history),
            first_moved_at_ns=history[0][0],
            detected_at_ns=now_ns,
            ports=tuple(ports),
        )

    def movements(self, switch_id: str, mac: int, now_ns: int) -> int:
        key = (switch_id, mac)
        history = self._history.get(key, [])
        cutoff = now_ns - self._window_ns
        return sum(1 for entry in history if entry[0] >= cutoff)

    def reset(self, switch_id: str | None = None, mac: int | None = None) -> None:
        if switch_id is None and mac is None:
            self._history.clear()
            self._flapping.clear()
            return
        for key in tuple(self._history):
            if (switch_id is None or key[0] == switch_id) and (mac is None or key[1] == mac):
                self._history.pop(key, None)
                self._flapping.discard(key)


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
