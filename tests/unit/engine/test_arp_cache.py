import pytest

from app.engine.arp.cache import ARP_CACHE_LIFETIME_NS, ArpCache, ArpUpdateOutcome
from app.engine.ethernet.mac import BROADCAST_MAC, parse_mac
from app.engine.ipv4.address import InvalidIPv4AddressError, parse_ipv4

IP_A = parse_ipv4("192.168.1.10")
IP_B = parse_ipv4("192.168.1.20")
MAC_A = parse_mac("02:00:00:00:00:0a")
MAC_B = parse_mac("02:00:00:00:00:0b")


def test_fresh_cache_is_empty():
    cache = ArpCache()

    assert len(cache) == 0
    assert cache.lookup(IP_A, 0) is None


def test_update_new_refreshed_and_changed():
    cache = ArpCache()

    first = cache.update(IP_A, MAC_A, 0)
    assert (first.outcome, first.previous_mac) == (ArpUpdateOutcome.NEW, None)

    same = cache.update(IP_A, MAC_A, 10)
    assert (same.outcome, same.previous_mac) == (ArpUpdateOutcome.REFRESHED, MAC_A)

    changed = cache.update(IP_A, MAC_B, 20)
    assert (changed.outcome, changed.previous_mac) == (ArpUpdateOutcome.CHANGED, MAC_A)
    assert cache.lookup(IP_A, 20) == MAC_B


def test_entry_expires_60s_after_last_update():
    cache = ArpCache()
    cache.update(IP_A, MAC_A, 1_000)

    assert cache.lookup(IP_A, 1_000 + ARP_CACHE_LIFETIME_NS - 1) == MAC_A
    assert cache.lookup(IP_A, 1_000 + ARP_CACHE_LIFETIME_NS) is None
    assert len(cache) == 0


def test_lookup_does_not_extend_lifetime():
    cache = ArpCache()
    cache.update(IP_A, MAC_A, 0)

    assert cache.lookup(IP_A, ARP_CACHE_LIFETIME_NS - 1) == MAC_A
    assert cache.lookup(IP_A, ARP_CACHE_LIFETIME_NS) is None


def test_update_extends_only_that_entry():
    cache = ArpCache()
    cache.update(IP_A, MAC_A, 0)
    cache.update(IP_B, MAC_B, 0)
    cache.update(IP_A, MAC_A, ARP_CACHE_LIFETIME_NS - 1)

    assert cache.lookup(IP_A, ARP_CACHE_LIFETIME_NS) == MAC_A
    assert cache.lookup(IP_B, ARP_CACHE_LIFETIME_NS) is None


def test_update_after_expiry_is_new():
    cache = ArpCache()
    cache.update(IP_A, MAC_A, 0)

    result = cache.update(IP_A, MAC_B, ARP_CACHE_LIFETIME_NS)

    assert (result.outcome, result.previous_mac) == (ArpUpdateOutcome.NEW, None)


def test_caches_are_independent_per_device():
    pc = ArpCache()
    server = ArpCache()
    pc.update(IP_A, MAC_A, 0)

    assert server.lookup(IP_A, 0) is None


def test_rejects_group_mac_and_bad_inputs():
    cache = ArpCache()

    with pytest.raises(ValueError):
        cache.update(IP_A, BROADCAST_MAC, 0)
    with pytest.raises(InvalidIPv4AddressError):
        cache.update(-1, MAC_A, 0)
    with pytest.raises(InvalidIPv4AddressError):
        cache.lookup(2**32, 0)
    with pytest.raises(ValueError):
        cache.update(IP_A, MAC_A, -1)
    with pytest.raises(ValueError):
        cache.lookup(IP_A, 1.5)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_lifetime", [0, -1, 1.5, True])
def test_invalid_lifetime_is_rejected(bad_lifetime):
    with pytest.raises(ValueError):
        ArpCache(bad_lifetime)
