import pytest

from app.engine.clock.queue import EventQueue


def drain(queue: EventQueue[str]) -> list[str]:
    result = []
    while len(queue):
        result.append(queue.pop().event.payload)
    return result


def test_orders_by_time_then_phase_then_creation_sequence():
    queue: EventQueue[str] = EventQueue()
    queue.schedule(2_000, 10, "late")
    queue.schedule(1_000, 30, "t1-p30")
    queue.schedule(1_000, 10, "t1-p10-first")
    queue.schedule(1_000, 10, "t1-p10-second")

    assert drain(queue) == ["t1-p10-first", "t1-p10-second", "t1-p30", "late"]


def test_execution_index_is_monotone_and_clock_advances():
    queue: EventQueue[str] = EventQueue()
    queue.schedule(500, 20, "a")
    queue.schedule(900, 20, "b")

    first = queue.pop()
    assert (first.execution_index, queue.now_ns) == (0, 500)

    second = queue.pop()
    assert (second.execution_index, queue.now_ns) == (1, 900)


def test_same_input_gives_same_order():
    def run() -> list[str]:
        queue: EventQueue[str] = EventQueue()
        for time_ns, phase, name in [(3, 20, "c"), (1, 40, "b"), (1, 10, "a"), (3, 20, "d")]:
            queue.schedule(time_ns, phase, name)
        return drain(queue)

    assert run() == run() == ["a", "b", "c", "d"]


def test_rejects_past_time():
    queue: EventQueue[str] = EventQueue()
    queue.schedule(1_000, 10, "x")
    queue.pop()

    with pytest.raises(ValueError, match="past"):
        queue.schedule(999, 10, "y")


@pytest.mark.parametrize("bad_time", [1.5, True, "10", None])
def test_rejects_non_int_time(bad_time):
    queue: EventQueue[str] = EventQueue()

    with pytest.raises(TypeError):
        queue.schedule(bad_time, 10, "x")


def test_rejects_negative_time_and_invalid_phase():
    queue: EventQueue[str] = EventQueue()

    with pytest.raises(ValueError):
        queue.schedule(-1, 10, "x")
    with pytest.raises(ValueError, match="phase"):
        queue.schedule(0, 15, "x")


def test_pop_empty_raises():
    with pytest.raises(IndexError):
        EventQueue[str]().pop()


def test_discard_pending_returns_selection_order_and_empties():
    queue: EventQueue[str] = EventQueue()
    queue.schedule(2, 10, "b")
    queue.schedule(1, 10, "a")

    discarded = queue.discard_pending()

    assert [e.payload for e in discarded] == ["a", "b"]
    assert len(queue) == 0
