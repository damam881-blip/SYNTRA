import pytest

from app.engine.ethernet.mac import (
    BROADCAST_MAC,
    InvalidMacAddressError,
    format_mac,
    is_broadcast,
    is_group_address,
    parse_mac,
)
from app.engine.ethernet.switch_table import (
    MAC_AGING_NS,
    ForwardAction,
    LearnOutcome,
    SwitchMacTable,
)

A = parse_mac("02:00:00:00:00:0a")
B = parse_mac("02:00:00:00:00:0b")
C = parse_mac("02:00:00:00:00:0c")
PORTS = ("p1", "p2", "p3")


# --- MAC primitives -------------------------------------------------------------------


def test_mac_roundtrip_and_case_insensitive_input():
    assert format_mac(parse_mac("AA:BB:CC:DD:EE:FF")) == "aa:bb:cc:dd:ee:ff"
    assert parse_mac("00:00:00:00:00:00") == 0


@pytest.mark.parametrize(
    "bad",
    ["", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "aa:bb:cc:dd:ee:f", "gg:bb:cc:dd:ee:ff",
     "aabb.ccdd.eeff", " aa:bb:cc:dd:ee:ff", "aa-bb-cc-dd-ee-ff"],
)  # fmt: skip
def test_mac_rejects_malformed(bad):
    with pytest.raises(InvalidMacAddressError):
        parse_mac(bad)


def test_broadcast_and_group_bit():
    assert is_broadcast(BROADCAST_MAC)
    assert is_group_address(BROADCAST_MAC)
    assert is_group_address(parse_mac("01:00:5e:00:00:01"))
    assert not is_group_address(A)
    assert not is_broadcast(A)


# --- Learning and aging ---------------------------------------------------------------


def test_learn_new_refreshed_and_moved():
    table = SwitchMacTable()

    first = table.learn(A, "p1", 0)
    assert (first.outcome, first.previous_port) == (LearnOutcome.NEW, None)

    again = table.learn(A, "p1", 10)
    assert (again.outcome, again.previous_port) == (LearnOutcome.REFRESHED, "p1")

    moved = table.learn(A, "p2", 20)
    assert (moved.outcome, moved.previous_port) == (LearnOutcome.MOVED, "p1")
    assert table.lookup(A, 20) == "p2"


def test_entry_expires_300s_after_last_learning():
    table = SwitchMacTable()
    table.learn(A, "p1", 1_000)

    assert table.lookup(A, 1_000 + MAC_AGING_NS - 1) == "p1"
    assert table.lookup(A, 1_000 + MAC_AGING_NS) is None
    assert len(table) == 0


def test_refresh_extends_only_that_entry():
    table = SwitchMacTable()
    table.learn(A, "p1", 0)
    table.learn(B, "p2", 0)
    table.learn(A, "p1", MAC_AGING_NS - 1)  # refresh A only

    assert table.lookup(A, MAC_AGING_NS) == "p1"
    assert table.lookup(B, MAC_AGING_NS) is None


def test_relearning_after_expiry_is_new():
    table = SwitchMacTable()
    table.learn(A, "p1", 0)

    result = table.learn(A, "p2", MAC_AGING_NS)

    assert (result.outcome, result.previous_port) == (LearnOutcome.NEW, None)


def test_rejects_group_source_and_bad_inputs():
    table = SwitchMacTable()

    with pytest.raises(InvalidMacAddressError):
        table.learn(BROADCAST_MAC, "p1", 0)
    with pytest.raises(ValueError):
        table.learn(A, "", 0)
    with pytest.raises(ValueError):
        table.learn(A, "p1", -1)
    with pytest.raises(ValueError):
        table.learn(A, "p1", 1.5)  # type: ignore[arg-type]


# --- Forwarding decisions -------------------------------------------------------------


def test_unknown_unicast_floods_except_ingress_in_given_order():
    table = SwitchMacTable()

    learn, decision = table.decide(
        ingress_port="p2", source_mac=A, destination_mac=B, eligible_ports=PORTS, now_ns=0
    )

    assert learn.outcome == LearnOutcome.NEW
    assert decision.action == ForwardAction.FLOOD
    assert decision.egress_ports == ("p1", "p3")


def test_broadcast_floods_even_if_table_has_entries():
    table = SwitchMacTable()
    table.learn(B, "p3", 0)

    _, decision = table.decide(
        ingress_port="p1",
        source_mac=A,
        destination_mac=BROADCAST_MAC,
        eligible_ports=PORTS,
        now_ns=1,
    )

    assert decision.action == ForwardAction.FLOOD
    assert decision.egress_ports == ("p2", "p3")


def test_known_unicast_goes_only_to_learned_port():
    table = SwitchMacTable()
    table.learn(B, "p3", 0)

    _, decision = table.decide(
        ingress_port="p1", source_mac=A, destination_mac=B, eligible_ports=PORTS, now_ns=1
    )

    assert decision.action == ForwardAction.UNICAST
    assert decision.egress_ports == ("p3",)


def test_expired_destination_is_flooded_again():
    table = SwitchMacTable()
    table.learn(B, "p3", 0)

    _, decision = table.decide(
        ingress_port="p1",
        source_mac=A,
        destination_mac=B,
        eligible_ports=PORTS,
        now_ns=MAC_AGING_NS,
    )

    assert decision.action == ForwardAction.FLOOD


def test_destination_behind_ingress_is_filtered():
    table = SwitchMacTable()
    table.learn(B, "p1", 0)

    _, decision = table.decide(
        ingress_port="p1", source_mac=A, destination_mac=B, eligible_ports=PORTS, now_ns=1
    )

    assert decision.action == ForwardAction.FILTER
    assert decision.egress_ports == ()


def test_learned_port_not_eligible_floods():
    table = SwitchMacTable()
    table.learn(C, "p3", 0)

    _, decision = table.decide(
        ingress_port="p1",
        source_mac=A,
        destination_mac=C,
        eligible_ports=("p1", "p2"),
        now_ns=1,
    )

    assert decision.action == ForwardAction.FLOOD
    assert decision.egress_ports == ("p2",)


def test_source_is_learned_before_forwarding():
    table = SwitchMacTable()

    table.decide(ingress_port="p1", source_mac=A, destination_mac=B, eligible_ports=PORTS, now_ns=5)

    assert table.lookup(A, 5) == "p1"


@pytest.mark.parametrize("bad_ports", [{"p1", "p2"}, frozenset({"p1"}), "p1p2"])
def test_unordered_eligible_ports_are_rejected(bad_ports):
    table = SwitchMacTable()

    with pytest.raises(TypeError):
        table.decide(
            ingress_port="p1", source_mac=A, destination_mac=B, eligible_ports=bad_ports, now_ns=0
        )


def test_same_input_same_decision():
    def run():
        table = SwitchMacTable()
        table.learn(B, "p3", 0)
        return table.decide(
            ingress_port="p1", source_mac=A, destination_mac=B, eligible_ports=PORTS, now_ns=7
        )

    assert run() == run()
