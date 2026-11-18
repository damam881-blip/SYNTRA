import heapq
from dataclasses import dataclass

# Phase values per TASK-03 §4.3A (meanings defined upstream).
ALLOWED_PHASES = frozenset({10, 20, 30, 40, 50, 60})


def _require_int(name: str, value: object) -> None:
    # `type(...) is int` rejects bool and float on purpose (no float time).
    if type(value) is not int:
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ScheduledEvent[T]:
    virtual_time_ns: int
    phase: int
    creation_sequence: int
    payload: T


@dataclass(frozen=True, slots=True)
class ExecutedEvent[T]:
    execution_index: int
    event: ScheduledEvent[T]


class EventQueue[T]:
    """Deterministic virtual-time event queue.

    Selection key: (virtual_time_ns, phase, creation_sequence)  -- PROPOSED.
    execution_index is assigned only when an event is actually popped.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, ScheduledEvent[T]]] = []
        self._now_ns = 0
        self._next_creation_sequence = 0
        self._next_execution_index = 0

    @property
    def now_ns(self) -> int:
        return self._now_ns

    def __len__(self) -> int:
        return len(self._heap)

    def schedule(self, virtual_time_ns: int, phase: int, payload: T) -> ScheduledEvent[T]:
        _require_int("virtual_time_ns", virtual_time_ns)
        _require_int("phase", phase)
        if virtual_time_ns < self._now_ns:
            raise ValueError(f"cannot schedule in the past: {virtual_time_ns} < now {self._now_ns}")
        if phase not in ALLOWED_PHASES:
            raise ValueError(f"invalid phase: {phase}")

        event = ScheduledEvent(
            virtual_time_ns=virtual_time_ns,
            phase=phase,
            creation_sequence=self._next_creation_sequence,
            payload=payload,
        )
        self._next_creation_sequence += 1
        # creation_sequence is unique, so payloads are never compared.
        heapq.heappush(self._heap, (virtual_time_ns, phase, event.creation_sequence, event))
        return event

    def pop(self) -> ExecutedEvent[T]:
        if not self._heap:
            raise IndexError("pop from empty EventQueue")

        event = heapq.heappop(self._heap)[3]
        self._now_ns = event.virtual_time_ns
        executed = ExecutedEvent(execution_index=self._next_execution_index, event=event)
        self._next_execution_index += 1
        return executed

    def discard_pending(self) -> list[ScheduledEvent[T]]:
        """Deterministic closure: drop residual events, returned in selection order."""
        pending = [entry[3] for entry in sorted(self._heap, key=lambda e: e[:3])]
        self._heap.clear()
        return pending
