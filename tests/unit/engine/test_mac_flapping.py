"""MAC flapping evidence: 3 source-port movements within 1000 virtual ms."""

import pytest

from app.engine.ethernet.mac import InvalidMacAddressError, parse_mac
from app.engine.ethernet.switch_table import MacFlapDetector

MAC = parse_mac("02:00:00:00:00:0a")


def move(detector, now_ns, previous, new, switch_id="sw1"):
    return detector.record_movement(
        switch_id=switch_id,
        mac=MAC,
        previous_port=previous,
        new_port=new,
        now_ns=now_ns,
    )


def test_three_movements_within_window_emit_one_event():
    detector = MacFlapDetector()

    assert move(detector, 0, "p1", "p2") is None
    assert move(detector, 100, "p2", "p3") is None
    event = move(detector, 200, "p3", "p1")

    assert event is not None
    assert event.switch_id == "sw1"
    assert event.mac == MAC
    assert event.movements == 3
    assert event.first_moved_at_ns == 0
    assert event.detected_at_ns == 200
    assert event.ports == ("p1", "p2", "p3", "p1")


def test_repeated_movement_while_flapping_does_not_duplicate_event():
    detector = MacFlapDetector()
    move(detector, 0, "p1", "p2")
    move(detector, 100, "p2", "p3")
    assert move(detector, 200, "p3", "p1") is not None

    assert move(detector, 300, "p1", "p2") is None
    assert move(detector, 400, "p2", "p3") is None


def test_movements_outside_window_do_not_trigger():
    detector = MacFlapDetector()

    assert move(detector, 0, "p1", "p2") is None
    assert move(detector, 100, "p2", "p3") is None
    assert move(detector, 1_000_000_001, "p3", "p1") is None


def test_flapping_can_be_detected_again_after_window_slides():
    detector = MacFlapDetector()
    move(detector, 0, "p1", "p2")
    move(detector, 100, "p2", "p3")
    assert move(detector, 200, "p3", "p1") is not None

    assert move(detector, 2_000_000_000, "p1", "p2") is None
    assert move(detector, 2_000_000_100, "p2", "p3") is None
    assert move(detector, 2_000_000_200, "p3", "p1") is not None


def test_movement_count_uses_only_window():
    detector = MacFlapDetector()
    move(detector, 0, "p1", "p2")
    move(detector, 500, "p2", "p3")

    assert detector.movements("sw1", MAC, 500) == 2
    assert detector.movements("sw1", MAC, 1_000_000_501) == 0


def test_detectors_are_scoped_by_switch_and_mac():
    detector = MacFlapDetector()
    move(detector, 0, "p1", "p2", switch_id="sw1")
    move(detector, 100, "p2", "p3", switch_id="sw2")

    assert detector.movements("sw1", MAC, 100) == 1
    assert detector.movements("sw2", MAC, 100) == 1


def test_reset_clears_history():
    detector = MacFlapDetector()
    move(detector, 0, "p1", "p2")

    detector.reset("sw1", MAC)

    assert detector.movements("sw1", MAC, 0) == 0


def test_same_port_and_group_mac_are_rejected():
    detector = MacFlapDetector()

    with pytest.raises(ValueError):
        move(detector, 0, "p1", "p1")
    with pytest.raises(InvalidMacAddressError):
        detector.record_movement(
            switch_id="sw1",
            mac=parse_mac("ff:ff:ff:ff:ff:ff"),
            previous_port="p1",
            new_port="p2",
            now_ns=0,
        )
