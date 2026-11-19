"""Tests for deterministic virtual-time scheduling and runtime safety."""

from __future__ import annotations

import pytest

from app.engine.clock import (
    BranchTraversalLimitExceeded,
    EventBudgetExhausted,
    EventQueue,
    RetryContext,
    RetryPolicy,
    RuntimeFrozenError,
    Timer,
    VirtualClock,
    transmission_delay_ns,
)


def drain(queue: EventQueue[str]) -> list[str]:
    result: list[str] = []
    while len(queue):
        result.append(queue.pop().event.payload)
    return result


def test_orders_by_time_phase_and_creation_sequence() -> None:
    queue: EventQueue[str] = EventQueue()
    queue.schedule(2_000, 10, "late")
    queue.schedule(1_000, 30, "t1-p30")
    queue.schedule(1_000, 10, "t1-p10-first")
    queue.schedule(1_000, 10, "t1-p10-second")

    assert drain(queue) == ["t1-p10-first", "t1-p10-second", "t1-p30", "late"]


def test_execution_index_is_separate_from_selection_key() -> None:
    queue: EventQueue[str] = EventQueue()
    queue.schedule(500, 20, "a")
    queue.schedule(900, 20, "b")

    first = queue.pop()
    second = queue.pop()

    assert (first.execution_index, first.event.virtual_time_ns) == (0, 500)
    assert (second.execution_index, second.event.virtual_time_ns) == (1, 900)
    assert first.event.creation_sequence == 0
    assert second.event.creation_sequence == 1


def test_event_ids_are_unique_and_monotonic() -> None:
    queue: EventQueue[str] = EventQueue()
    first = queue.schedule(1, 10, "a")
    second = queue.schedule(2, 10, "b")

    assert first.event_id == 1
    assert second.event_id == 2
    assert first.event_id != second.event_id


def test_causal_lineage_is_preserved() -> None:
    queue: EventQueue[str] = EventQueue()
    parent = queue.schedule(10, 10, "parent")
    child = queue.schedule(20, 20, "child", parent_event_id=parent.event_id)

    assert child.parent_event_id == parent.event_id
    assert child.root_event_id == parent.event_id
    assert child.causal_depth == 1
    assert child.event_id is not None


def test_run_until_includes_deadline_boundary() -> None:
    queue: EventQueue[str] = EventQueue()
    queue.schedule(1_000, 10, "before")
    queue.schedule(2_000, 10, "at-deadline")
    queue.schedule(2_001, 10, "after")

    executed = queue.run_until(2_000)

    assert [event.event.payload for event in executed] == ["before", "at-deadline"]
    assert queue.now_ns == 2_000
    assert len(queue) == 1


def test_run_until_closes_same_timestamp_lower_phase() -> None:
    queue: EventQueue[str] = EventQueue()
    queue.schedule(100, 40, "outer")
    executed = queue.run_until(100)

    assert [event.event.payload for event in executed] == ["outer"]
    assert queue.now_ns == 100


def test_budgets_are_enforced_and_cancellation_does_not_refund() -> None:
    queue: EventQueue[str] = EventQueue(request_event_budget=2, test_event_budget=3)
    first = queue.schedule(1, 10, "first")
    queue.schedule(2, 10, "second")

    assert queue.cancel_event(first.event_id or 0) is True

    with __import__("pytest").raises(EventBudgetExhausted):
        queue.schedule(3, 10, "third")

    assert queue.remaining_request_budget == 0
    assert queue.remaining_test_budget == 1


def test_branch_traversal_limit_is_enforced() -> None:
    queue: EventQueue[str] = EventQueue(branch_traversal_limit=2)

    assert queue.record_branch_traversal() == 1
    assert queue.record_branch_traversal() == 2

    with pytest.raises(BranchTraversalLimitExceeded):
        queue.record_branch_traversal()


def test_freeze_prevents_scheduling() -> None:
    queue: EventQueue[str] = EventQueue()
    queue.freeze()

    assert queue.is_frozen() is True
    with __import__("pytest").raises(RuntimeFrozenError):
        queue.schedule(1, 10, "blocked")


def test_transmission_delays_are_exact() -> None:
    assert transmission_delay_ns(78, 100_000_000) == 6240
    assert transmission_delay_ns(78, 1_000_000_000) == 624
    assert transmission_delay_ns(74, 100_000_000) == 5920
    assert transmission_delay_ns(74, 1_000_000_000) == 592


def test_virtual_clock_uses_integer_nanoseconds() -> None:
    clock = VirtualClock(now_ns=100)
    clock.advance_to(200)
    assert clock.now_ns == 200

    with __import__("pytest").raises(ValueError):
        clock.advance_to(150)


def test_retry_policy_is_deterministic() -> None:
    policy = RetryPolicy(max_attempts=2, interval_ns=100_000_000)
    assert policy.due_times(0) == (0, 100_000_000)

    context = RetryContext(attempt=1, max_attempts=2, interval_ns=100_000_000, due_at_ns=0)
    assert context.has_next_attempt() is True
    assert context.next_due_at_ns() == 100_000_000


def test_timer_and_retry_scheduling() -> None:
    queue: EventQueue[str] = EventQueue()
    timer = Timer(due_at_ns=500, phase=10, payload="timer")
    event = queue.schedule_timer(timer)
    assert (event.virtual_time_ns, event.phase, event.payload) == (500, 10, "timer")

    retries = queue.schedule_retry(
        0, 10, "retry", policy=RetryPolicy(max_attempts=2, interval_ns=100)
    )
    assert [(event.virtual_time_ns, event.payload) for event in retries] == [
        (0, "retry"),
        (100, "retry"),
    ]


def test_run_observation_uses_inclusive_horizon() -> None:
    queue: EventQueue[str] = EventQueue()
    queue.schedule(10, 10, "near")
    queue.schedule(20, 10, "far")

    executed = queue.run_observation(15)

    assert [event.event.payload for event in executed] == ["near"]
    assert queue.now_ns == 10
