"""Deterministic virtual-time event queue and runtime scheduling primitives.

The scheduler uses integer nanoseconds only. Selection order is
``(virtual_time_ns, phase, creation_sequence)``; ``execution_index`` is assigned
only when an event is actually popped and is never used as a selection key.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")

# Approved TASK-03 phase priorities.
ALLOWED_PHASES = frozenset({10, 20, 30, 40, 50, 60})

# Approved timing constants (nanoseconds).
LINK_PROPAGATION_NS = 10_000
SWITCH_PROCESSING_NS = 50_000
ROUTER_PROCESSING_NS = 100_000
ENDPOINT_ICMP_PROCESSING_NS = 50_000
ARP_PROCESSING_NS = 50_000
ARP_RETRY_INTERVAL_NS = 100_000_000
ARP_RESOLUTION_WINDOW_NS = 200_000_000
PING_DEADLINE_NS = 1_000_000_000
OBSERVATION_HORIZON_NS = 1_000_000_000

# Approved safety budgets.
REQUEST_EVENT_BUDGET = 10_000
TEST_EVENT_BUDGET = 40_000
BRANCH_TRAVERSAL_LIMIT = 128

# Approved frame sizes (bytes).
ICMP_ECHO_FRAME_BYTES = 78
ARP_FRAME_BYTES = 64
ICMP_TIME_EXCEEDED_FRAME_BYTES = 74

FAST_ETHERNET_BITRATE_BPS = 100_000_000
GIGABIT_ETHERNET_BITRATE_BPS = 1_000_000_000


class EventBudgetExhausted(Exception):
    """Raised when a request or test event budget would be exceeded."""


class BranchTraversalLimitExceeded(Exception):
    """Raised when a branch traversal count exceeds its safety limit."""


class RuntimeFrozenError(Exception):
    """Raised when scheduling is attempted after runtime freeze."""


@dataclass(slots=True)
class VirtualClock:
    """Integer-nanosecond virtual clock. It never uses wall-clock time."""

    now_ns: int = 0

    def advance_to(self, time_ns: int) -> None:
        _require_int("time_ns", time_ns)
        if time_ns < self.now_ns:
            raise ValueError(f"cannot move virtual clock backwards: {time_ns} < {self.now_ns}")
        self.now_ns = time_ns

    def advance_by(self, delta_ns: int) -> None:
        _require_int("delta_ns", delta_ns)
        if delta_ns < 0:
            raise ValueError("delta_ns must be non-negative")
        self.now_ns += delta_ns


@dataclass(frozen=True, slots=True)
class ScheduledEvent[T]:
    virtual_time_ns: int
    phase: int
    creation_sequence: int
    payload: T
    event_id: int | None = None
    parent_event_id: int | None = None
    root_event_id: int | None = None
    causal_depth: int = 0


@dataclass(frozen=True, slots=True)
class ExecutedEvent[T]:
    execution_index: int
    event: ScheduledEvent[T]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Deterministic retry policy. Due times are derived, never wall-clock based."""

    max_attempts: int = 2
    interval_ns: int = ARP_RETRY_INTERVAL_NS

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive int")
        if (
            isinstance(self.interval_ns, bool)
            or not isinstance(self.interval_ns, int)
            or self.interval_ns < 0
        ):
            raise ValueError("interval_ns must be a non-negative int")

    def due_times(self, start_ns: int) -> tuple[int, ...]:
        _require_int("start_ns", start_ns)
        if start_ns < 0:
            raise ValueError("start_ns must be non-negative")
        return tuple(start_ns + attempt * self.interval_ns for attempt in range(self.max_attempts))


@dataclass(frozen=True, slots=True)
class RetryContext:
    attempt: int
    max_attempts: int
    interval_ns: int
    due_at_ns: int

    def has_next_attempt(self) -> bool:
        return self.attempt < self.max_attempts

    def next_due_at_ns(self) -> int | None:
        if not self.has_next_attempt():
            return None
        return self.due_at_ns + self.interval_ns


_DEFAULT_RETRY_POLICY = RetryPolicy()


@dataclass(frozen=True, slots=True)
class Timer:
    due_at_ns: int
    phase: int
    payload: Any = None

    def __post_init__(self) -> None:
        _require_int("due_at_ns", self.due_at_ns)
        if self.due_at_ns < 0:
            raise ValueError("due_at_ns must be non-negative")
        if self.phase not in ALLOWED_PHASES:
            raise ValueError(f"invalid phase: {self.phase}")


def transmission_delay_ns(frame_bytes: int, bitrate_bps: int) -> int:
    """Return serialization delay in nanoseconds using exact integer arithmetic."""
    _require_int("frame_bytes", frame_bytes)
    _require_int("bitrate_bps", bitrate_bps)
    if frame_bytes < 0:
        raise ValueError("frame_bytes must be non-negative")
    if bitrate_bps <= 0:
        raise ValueError("bitrate_bps must be positive")
    return (frame_bytes * 8 * 1_000_000_000) // bitrate_bps


def transmission_delay(frame_bytes: int, bitrate_bps: int) -> int:
    return transmission_delay_ns(frame_bytes, bitrate_bps)


class EventQueue[T]:
    """Deterministic virtual-time event queue with optional budgets and closure."""

    def __init__(
        self,
        *,
        request_event_budget: int | None = REQUEST_EVENT_BUDGET,
        test_event_budget: int | None = TEST_EVENT_BUDGET,
        branch_traversal_limit: int = BRANCH_TRAVERSAL_LIMIT,
        clock: VirtualClock | None = None,
    ) -> None:
        if request_event_budget is not None and (
            isinstance(request_event_budget, bool)
            or not isinstance(request_event_budget, int)
            or request_event_budget < 1
        ):
            raise ValueError("request_event_budget must be a positive int or None")
        if test_event_budget is not None and (
            isinstance(test_event_budget, bool)
            or not isinstance(test_event_budget, int)
            or test_event_budget < 1
        ):
            raise ValueError("test_event_budget must be a positive int or None")
        if (
            isinstance(branch_traversal_limit, bool)
            or not isinstance(branch_traversal_limit, int)
            or branch_traversal_limit < 1
        ):
            raise ValueError("branch_traversal_limit must be a positive int")

        self.clock = clock if clock is not None else VirtualClock()
        self._heap: list[tuple[int, int, int, ScheduledEvent[T]]] = []
        self._next_creation_sequence = 0
        self._next_execution_index = 0
        self._next_event_id = 1
        self._request_event_budget = request_event_budget
        self._test_event_budget = test_event_budget
        self._request_events_scheduled = 0
        self._test_events_scheduled = 0
        self._branch_traversal_limit = branch_traversal_limit
        self._branch_counts: dict[str, int] = {}
        self._canceled_event_ids: set[int] = set()
        self._frozen = False
        self._event_roots: dict[int, int] = {}
        self._event_depths: dict[int, int] = {}

    @property
    def now_ns(self) -> int:
        return self.clock.now_ns

    @property
    def _now_ns(self) -> int:
        # Backward-compatible read-only view for code that inspected the old field.
        return self.clock.now_ns

    def __len__(self) -> int:
        return len(self._heap)

    def advance_clock(self, time_ns: int) -> None:
        self.clock.advance_to(time_ns)

    def schedule(
        self,
        virtual_time_ns: int,
        phase: int,
        payload: T,
        *,
        event_id: int | None = None,
        parent_event_id: int | None = None,
        root_event_id: int | None = None,
        causal_depth: int = 0,
        branch_id: str | None = None,
    ) -> ScheduledEvent[T]:
        _require_int("virtual_time_ns", virtual_time_ns)
        _require_int("phase", phase)
        if self._frozen:
            raise RuntimeFrozenError("cannot schedule events after the runtime is frozen")
        if virtual_time_ns < self.now_ns:
            raise ValueError(f"cannot schedule in the past: {virtual_time_ns} < now {self.now_ns}")
        if phase not in ALLOWED_PHASES:
            raise ValueError(f"invalid phase: {phase}")
        if event_id is not None and (
            isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1
        ):
            raise ValueError("event_id must be a positive int or None")
        if parent_event_id is not None and (
            isinstance(parent_event_id, bool)
            or not isinstance(parent_event_id, int)
            or parent_event_id < 1
        ):
            raise ValueError("parent_event_id must be a positive int or None")
        if root_event_id is not None and (
            isinstance(root_event_id, bool)
            or not isinstance(root_event_id, int)
            or root_event_id < 1
        ):
            raise ValueError("root_event_id must be a positive int or None")
        if isinstance(causal_depth, bool) or not isinstance(causal_depth, int) or causal_depth < 0:
            raise ValueError("causal_depth must be a non-negative int")

        if (
            self._request_event_budget is not None
            and self._request_events_scheduled >= self._request_event_budget
        ):
            raise EventBudgetExhausted("request event budget exhausted")
        if (
            self._test_event_budget is not None
            and self._test_events_scheduled >= self._test_event_budget
        ):
            raise EventBudgetExhausted("test event budget exhausted")

        if event_id is None:
            event_id = self._next_event_id
            self._next_event_id += 1

        resolved_root_event_id = root_event_id
        resolved_causal_depth = causal_depth
        if parent_event_id is not None:
            if resolved_root_event_id is None:
                resolved_root_event_id = self._event_roots.get(parent_event_id, parent_event_id)
            if resolved_causal_depth == 0:
                resolved_causal_depth = self._event_depths.get(parent_event_id, 0) + 1
        elif resolved_root_event_id is None:
            resolved_root_event_id = event_id

        event = ScheduledEvent(
            virtual_time_ns=virtual_time_ns,
            phase=phase,
            creation_sequence=self._next_creation_sequence,
            payload=payload,
            event_id=event_id,
            parent_event_id=parent_event_id,
            root_event_id=resolved_root_event_id,
            causal_depth=resolved_causal_depth,
        )
        self._next_creation_sequence += 1
        self._event_roots[event_id] = (
            resolved_root_event_id if resolved_root_event_id is not None else event_id
        )
        self._event_depths[event_id] = resolved_causal_depth

        if self._request_event_budget is not None:
            self._request_events_scheduled += 1
        if self._test_event_budget is not None:
            self._test_events_scheduled += 1

        if branch_id is not None:
            self.record_branch_traversal(branch_id)

        heapq.heappush(self._heap, (virtual_time_ns, phase, event.creation_sequence, event))
        return event

    def pop(self) -> ExecutedEvent[T]:
        while self._heap:
            event = heapq.heappop(self._heap)[3]
            if event.event_id is not None and event.event_id in self._canceled_event_ids:
                self._canceled_event_ids.discard(event.event_id)
                continue
            self.clock.advance_to(event.virtual_time_ns)
            executed = ExecutedEvent(execution_index=self._next_execution_index, event=event)
            self._next_execution_index += 1
            return executed
        raise IndexError("pop from empty EventQueue")

    def run_until(self, time_ns: int) -> list[ExecutedEvent[T]]:
        _require_int("time_ns", time_ns)
        if time_ns < self.now_ns:
            raise ValueError(f"cannot run backwards: {time_ns} < now {self.now_ns}")
        executed: list[ExecutedEvent[T]] = []
        while self._heap and self._heap[0][0] <= time_ns:
            executed.append(self.pop())
        return executed

    def run_all(self) -> list[ExecutedEvent[T]]:
        executed: list[ExecutedEvent[T]] = []
        while self._heap:
            executed.append(self.pop())
        return executed

    def drain(self) -> list[ExecutedEvent[T]]:
        return self.run_all()

    def discard_pending(self) -> list[ScheduledEvent[T]]:
        """Drop residual events in selection order. Budgets are not refunded."""
        pending = [entry[3] for entry in sorted(self._heap, key=lambda entry: entry[:3])]
        self._heap.clear()
        return pending

    def cancel_event(self, event_id: int) -> bool:
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
            raise ValueError("event_id must be a positive int")
        self._canceled_event_ids.add(event_id)
        return any(event.event_id == event_id for entry in self._heap for event in (entry[3],))

    def freeze(self) -> None:
        self._frozen = True

    def is_frozen(self) -> bool:
        return self._frozen

    def record_branch_traversal(self, branch_id: str = "") -> int:
        key = branch_id if branch_id != "" else "__global__"
        count = self._branch_counts.get(key, 0) + 1
        if count > self._branch_traversal_limit:
            raise BranchTraversalLimitExceeded(
                f"branch traversal count {count} exceeds limit {self._branch_traversal_limit}"
            )
        self._branch_counts[key] = count
        return count

    def reset_branch_traversals(self, branch_id: str | None = None) -> None:
        if branch_id is None:
            self._branch_counts.clear()
        else:
            self._branch_counts.pop(branch_id, None)

    def reset_request_budget(self) -> None:
        self._request_events_scheduled = 0

    def reset_test_budget(self) -> None:
        self._test_events_scheduled = 0

    def start_request(self) -> None:
        self.reset_request_budget()

    def start_test(self) -> None:
        self.reset_request_budget()
        self.reset_test_budget()

    def run_observation(self, duration_ns: int = OBSERVATION_HORIZON_NS) -> list[ExecutedEvent[T]]:
        _require_int("duration_ns", duration_ns)
        if duration_ns < 0:
            raise ValueError("duration_ns must be non-negative")
        return self.run_until(self.now_ns + duration_ns)

    def observe_for(self, duration_ns: int = OBSERVATION_HORIZON_NS) -> list[ExecutedEvent[T]]:
        return self.run_observation(duration_ns)

    def schedule_retry(
        self,
        start_ns: int,
        phase: int,
        payload: T,
        *,
        policy: RetryPolicy = _DEFAULT_RETRY_POLICY,
        parent_event_id: int | None = None,
        root_event_id: int | None = None,
        causal_depth: int = 0,
        branch_id: str | None = None,
    ) -> tuple[ScheduledEvent[T], ...]:
        return tuple(
            self.schedule(
                due_at_ns,
                phase,
                payload,
                parent_event_id=parent_event_id,
                root_event_id=root_event_id,
                causal_depth=causal_depth if causal_depth != 0 else attempt,
                branch_id=branch_id,
            )
            for attempt, due_at_ns in enumerate(policy.due_times(start_ns), start=1)
        )

    def schedule_timer(self, timer: Timer, payload: T | None = None) -> ScheduledEvent[T]:
        actual_payload = timer.payload if payload is None else payload
        return self.schedule(timer.due_at_ns, timer.phase, actual_payload)

    @property
    def request_events_scheduled(self) -> int:
        return self._request_events_scheduled

    @property
    def test_events_scheduled(self) -> int:
        return self._test_events_scheduled

    @property
    def remaining_request_budget(self) -> int | None:
        if self._request_event_budget is None:
            return None
        return self._request_event_budget - self._request_events_scheduled

    @property
    def remaining_test_budget(self) -> int | None:
        if self._test_event_budget is None:
            return None
        return self._test_event_budget - self._test_events_scheduled


# Compatibility names for callers that use runtime-oriented vocabulary.
EventScheduler = EventQueue
DeterministicRuntime = EventQueue
VirtualEventScheduler = EventQueue


class BranchTraversalGuard:
    """Standalone safety guard with the same semantics as EventQueue.record_branch_traversal."""

    def __init__(self, limit: int = BRANCH_TRAVERSAL_LIMIT) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive int")
        self.limit = limit
        self._counts: dict[str, int] = {}

    def record(self, branch_id: str = "") -> int:
        key = branch_id if branch_id != "" else "__global__"
        count = self._counts.get(key, 0) + 1
        if count > self.limit:
            raise BranchTraversalLimitExceeded(
                f"branch traversal count {count} exceeds limit {self.limit}"
            )
        self._counts[key] = count
        return count

    def reset(self, branch_id: str | None = None) -> None:
        if branch_id is None:
            self._counts.clear()
        else:
            self._counts.pop(branch_id, None)


def _require_int(name: str, value: object) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
