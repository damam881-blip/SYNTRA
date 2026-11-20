"""Host gateway decision before ARP (TASK-03 §4.2)."""

import pytest

from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.ipv4.address import InvalidSubnetMaskError
from app.engine.ipv4.address import parse_ipv4 as ip
from app.engine.ipv4.address import parse_subnet_mask as mask
from app.engine.routing.host import HostForwardingStatus, decide_host_forwarding


def test_unconfigured_source_is_reported():
    decision = decide_host_forwarding(ip("10.0.0.2"), source_address=None, mask=None)

    assert decision.status is HostForwardingStatus.SOURCE_IPV4_UNCONFIGURED
    assert decision.diagnostic_code is DiagnosticCode.SOURCE_IPV4_UNCONFIGURED
    assert not decision.requires_arp


def test_local_and_on_link_destination():
    source = ip("192.168.10.10")
    subnet = mask("255.255.255.0")

    local = decide_host_forwarding(source, source_address=source, mask=subnet)
    direct = decide_host_forwarding(ip("192.168.10.20"), source_address=source, mask=subnet)

    assert local.status is HostForwardingStatus.LOCAL
    assert not local.requires_arp
    assert direct.status is HostForwardingStatus.DIRECT
    assert direct.next_hop == ip("192.168.10.20")
    assert direct.requires_arp


def test_remote_destination_uses_on_link_gateway():
    decision = decide_host_forwarding(
        ip("10.0.1.20"),
        source_address=ip("192.168.10.10"),
        mask=mask("255.255.255.0"),
        gateway=ip("192.168.10.1"),
    )

    assert decision.status is HostForwardingStatus.VIA_GATEWAY
    assert decision.next_hop == ip("192.168.10.1")
    assert decision.requires_arp


def test_missing_off_link_and_self_gateway_diagnostics():
    source = ip("192.168.10.10")
    subnet = mask("255.255.255.0")
    destination = ip("10.0.1.20")

    missing = decide_host_forwarding(destination, source_address=source, mask=subnet)
    off_link = decide_host_forwarding(
        destination, source_address=source, mask=subnet, gateway=ip("10.0.0.1")
    )
    self_reference = decide_host_forwarding(
        destination, source_address=source, mask=subnet, gateway=source
    )

    assert missing.status is HostForwardingStatus.MISSING_DEFAULT_GATEWAY
    assert missing.diagnostic_code is DiagnosticCode.MISSING_DEFAULT_GATEWAY
    assert off_link.status is HostForwardingStatus.OFF_LINK_DEFAULT_GATEWAY
    assert off_link.diagnostic_code is DiagnosticCode.OFF_LINK_DEFAULT_GATEWAY
    assert self_reference.status is HostForwardingStatus.SELF_REFERENCING_GATEWAY
    assert self_reference.diagnostic_code is DiagnosticCode.SELF_REFERENCING_GATEWAY
    assert not any(decision.is_usable for decision in (missing, off_link, self_reference))


def test_source_and_mask_must_be_configured_together():
    with pytest.raises(ValueError):
        decide_host_forwarding(ip("10.0.0.2"), source_address=ip("10.0.0.1"), mask=None)
    with pytest.raises(ValueError):
        decide_host_forwarding(ip("10.0.0.2"), source_address=None, mask=mask("255.255.255.0"))


def test_non_contiguous_mask_is_rejected():
    with pytest.raises(InvalidSubnetMaskError):
        decide_host_forwarding(ip("10.0.0.2"), source_address=ip("10.0.0.1"), mask=0xFF00FF00)
