"""Approved frame sizes, IPv4 TTL semantics and ICMP Echo correlation."""

import pytest

from app.engine.clock.queue import (
    ARP_FRAME_BYTES,
    ICMP_ECHO_FRAME_BYTES,
    ICMP_TIME_EXCEEDED_FRAME_BYTES,
    transmission_delay_ns,
)
from app.engine.ethernet.frame import (
    ETHERNET_FCS_BYTES,
    ETHERNET_HEADER_BYTES,
    FRAME_TOTAL_BYTES,
    EthernetFrame,
    FrameKind,
    frame_total_bytes,
)
from app.engine.ethernet.mac import BROADCAST_MAC, InvalidMacAddressError, parse_mac
from app.engine.icmp.messages import (
    ECHO_PAYLOAD_BYTES,
    EchoMessage,
    EchoReplyCorrelator,
    IcmpType,
    ReplyMatchOutcome,
    RequestCorrelation,
    TimeExceededMessage,
    build_echo_request,
    build_time_exceeded,
    icmp_error_allowed,
)
from app.engine.ipv4.address import InvalidIPv4AddressError
from app.engine.ipv4.address import parse_ipv4 as ip
from app.engine.ipv4.packet import INITIAL_ECHO_TTL, IpProtocol, Ipv4Packet, build_ipv4_packet

MAC_A = parse_mac("02:00:00:00:00:0a")
MAC_B = parse_mac("02:00:00:00:00:0b")


def test_frame_sizes_match_approved_totals():
    assert FRAME_TOTAL_BYTES[FrameKind.ARP] == ARP_FRAME_BYTES == 64
    assert FRAME_TOTAL_BYTES[FrameKind.ICMP_ECHO] == ICMP_ECHO_FRAME_BYTES == 78
    assert FRAME_TOTAL_BYTES[FrameKind.ICMP_TIME_EXCEEDED] == ICMP_TIME_EXCEEDED_FRAME_BYTES == 74
    assert frame_total_bytes(FrameKind.ICMP_ECHO) == 78


def test_echo_frame_decomposition():
    assert ETHERNET_HEADER_BYTES + 20 + 8 + ECHO_PAYLOAD_BYTES + ETHERNET_FCS_BYTES == 78


def test_frame_size_feeds_serialization_delay():
    echo_bytes = frame_total_bytes(FrameKind.ICMP_ECHO)
    time_exceeded_bytes = frame_total_bytes(FrameKind.ICMP_TIME_EXCEEDED)

    assert transmission_delay_ns(echo_bytes, 100_000_000) == 6_240
    assert transmission_delay_ns(echo_bytes, 1_000_000_000) == 624
    assert transmission_delay_ns(time_exceeded_bytes, 100_000_000) == 5_920
    assert transmission_delay_ns(time_exceeded_bytes, 1_000_000_000) == 592


def test_time_exceeded_frame_decomposition():
    assert ETHERNET_HEADER_BYTES + 20 + 8 + 20 + 8 + ETHERNET_FCS_BYTES == 74


def test_ethernet_frame_exposes_total_size():
    frame = EthernetFrame(BROADCAST_MAC, MAC_A, FrameKind.ARP)

    assert frame.total_bytes == 64
    assert frame.header_bytes == 14
    assert frame.fcs_bytes == 4


def test_ethernet_frame_rejects_group_source_and_bad_mac():
    with pytest.raises(InvalidMacAddressError):
        EthernetFrame(MAC_B, BROADCAST_MAC, FrameKind.ARP)
    with pytest.raises(InvalidMacAddressError):
        EthernetFrame(2**48, MAC_A, FrameKind.ARP)


def test_ipv4_packet_initial_ttl_and_transit():
    packet = build_ipv4_packet(ip("192.168.1.10"), ip("192.168.1.20"))

    assert packet.ttl == INITIAL_ECHO_TTL == 16
    assert packet.protocol is IpProtocol.ICMP
    assert not packet.expires_on_transit
    assert packet.forwarded().ttl == 15


@pytest.mark.parametrize("ttl", [0, 1])
def test_ipv4_packet_ttl_expiry(ttl):
    packet = Ipv4Packet(ip("10.0.0.1"), ip("10.0.0.2"), ttl=ttl)

    assert packet.expires_on_transit
    with pytest.raises(ValueError):
        packet.forwarded()


def test_ipv4_packet_local_delivery_and_validation():
    packet = Ipv4Packet(ip("10.0.0.1"), ip("10.0.0.2"))

    assert packet.is_locally_addressed(ip("10.0.0.2"))
    assert not packet.is_locally_addressed(ip("10.0.0.3"))
    with pytest.raises(ValueError):
        Ipv4Packet(ip("10.0.0.1"), ip("10.0.0.2"), ttl=256)
    with pytest.raises(InvalidIPv4AddressError):
        Ipv4Packet(-1, ip("10.0.0.2"))


def test_echo_request_and_reply_addresses_are_reversed():
    request = build_echo_request(
        ip("192.168.1.10"), ip("192.168.1.20"), identifier=0x1234, sequence=1
    )
    reply = request.as_reply()

    assert request.is_request and not request.is_reply
    assert reply.is_reply and reply.icmp_type is IcmpType.ECHO_REPLY
    assert (reply.source, reply.destination) == (ip("192.168.1.20"), ip("192.168.1.10"))
    assert (reply.identifier, reply.sequence) == (0x1234, 1)
    assert reply.payload_bytes == 32
    with pytest.raises(ValueError):
        reply.as_reply()


@pytest.mark.parametrize("sequence", [0, 5])
def test_echo_request_sequence_must_be_one_to_four(sequence):
    with pytest.raises(ValueError):
        build_echo_request(ip("10.0.0.1"), ip("10.0.0.2"), identifier=1, sequence=sequence)


def test_echo_identifier_is_16_bit():
    with pytest.raises(ValueError):
        build_echo_request(ip("10.0.0.1"), ip("10.0.0.2"), identifier=65536, sequence=1)
    with pytest.raises(ValueError):
        EchoMessage(IcmpType.ECHO_REQUEST, 1, 1, ip("10.0.0.1"), ip("10.0.0.2"), payload_bytes=31)


def test_reply_correlation_accepts_once_and_rejects_duplicates():
    request = RequestCorrelation(0x2222, 2, ip("10.0.0.1"), ip("10.0.0.2"))
    reply = build_echo_request(
        request.source, request.destination, identifier=request.test_id, sequence=request.sequence
    ).as_reply()
    correlator = EchoReplyCorrelator()

    assert correlator.match(reply, request) is ReplyMatchOutcome.MATCHED
    assert correlator.match(reply, request) is ReplyMatchOutcome.DUPLICATE
    assert correlator.is_matched(request)
    assert correlator.matched_count == 1


def test_reply_correlation_rejects_mismatches():
    request = RequestCorrelation(7, 3, ip("10.0.0.1"), ip("10.0.0.2"))
    base = build_echo_request(request.source, request.destination, identifier=7, sequence=3)
    correlator = EchoReplyCorrelator()

    wrong_identifier = build_echo_request(
        request.source, request.destination, identifier=8, sequence=3
    ).as_reply()
    wrong_sequence = build_echo_request(
        request.source, request.destination, identifier=7, sequence=2
    ).as_reply()
    wrong_source = EchoMessage(IcmpType.ECHO_REPLY, 7, 3, ip("10.0.0.9"), request.source)

    assert correlator.match(wrong_identifier, request) is ReplyMatchOutcome.MISMATCH
    assert correlator.match(wrong_sequence, request) is ReplyMatchOutcome.MISMATCH
    assert correlator.match(wrong_source, request) is ReplyMatchOutcome.MISMATCH
    assert correlator.match(base, request) is ReplyMatchOutcome.MISMATCH


def test_time_exceeded_message_quotes_eight_bytes():
    message = build_time_exceeded(
        router_address=ip("10.0.0.1"),
        original_source=ip("192.168.1.10"),
        original_destination=ip("10.0.1.20"),
        original_ttl=1,
    )

    assert isinstance(message, TimeExceededMessage)
    assert message.icmp_type is IcmpType.TIME_EXCEEDED
    assert message.code == 0
    assert message.is_icmp_error
    assert message.quote_bytes == 8
    assert (message.source, message.destination) == (ip("10.0.0.1"), ip("192.168.1.10"))


def test_icmp_errors_are_suppressed_for_non_unicast_and_errors():
    assert icmp_error_allowed(
        ip("192.168.1.10"), EchoMessage(IcmpType.ECHO_REQUEST, 1, 1, ip("10.0.0.1"), ip("10.0.0.2"))
    )
    assert not icmp_error_allowed(ip("224.0.0.1"), None)
    assert not icmp_error_allowed(ip("255.255.255.255"), None)
    error = build_time_exceeded(
        router_address=ip("10.0.0.1"),
        original_source=ip("10.0.0.2"),
        original_destination=ip("10.0.0.3"),
        original_ttl=1,
    )
    assert not icmp_error_allowed(ip("10.0.0.2"), error)
