import heapq


def test_equal_timestamp_events_have_deterministic_order():
    """Equal-time events follow an explicit sequence number."""
    events = [
        (1_000, 3, "event-c"),
        (1_000, 1, "event-a"),
        (1_000, 2, "event-b"),
    ]

    heapq.heapify(events)

    processed = []

    while events:
        _, _, event_name = heapq.heappop(events)
        processed.append(event_name)

    assert processed == [
        "event-a",
        "event-b",
        "event-c",
    ]


def test_event_order_is_repeatable():
    """The same event input produces the same order."""
    original_events = [
        (2_000, 2, "second"),
        (1_000, 3, "third"),
        (1_000, 1, "first"),
    ]

    def process_events():
        queue = original_events.copy()
        heapq.heapify(queue)

        result = []

        while queue:
            _, _, event_name = heapq.heappop(queue)
            result.append(event_name)

        return result

    first_run = process_events()
    second_run = process_events()

    assert first_run == second_run
    assert first_run == ["first", "third", "second"]
