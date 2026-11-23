"""TASK-02 structural rules are enforced by the TASK-06 mutation services."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.errors import ContractValidationError, IntegrityConflictError
from app.db.models import Connection, Interface, StaticRoute
from app.modules.projects.service import (
    add_connection,
    add_device,
    add_static_route,
    configure_interface_ipv4,
    create_project,
    edit_static_route,
    set_host_gateway,
)


def _project_with_devices(session, kinds):
    project = create_project(session, name="Validation Lab")
    devices = [
        add_device(session, project.project_id, kind=kind, display_name=f"D{index}")
        for index, kind in enumerate(kinds, start=1)
    ]
    session.commit()
    interfaces = [
        session.scalars(
            select(Interface)
            .where(Interface.device_id == device.device_id)
            .order_by(Interface.ordinal)
        ).first()
        for device in devices
    ]
    return project, devices, [interface.interface_id for interface in interfaces]


def test_incompatible_cable_is_rejected_without_mutation(session):
    project, _devices, interfaces = _project_with_devices(session, ["PC", "PC"])
    before = project.state_revision

    with pytest.raises(IntegrityConflictError):
        add_connection(
            session,
            project.project_id,
            interface_a_id=interfaces[0],
            interface_b_id=interfaces[1],
            cable_type="STRAIGHT_THROUGH",
        )
    session.rollback()

    assert project.state_revision == before
    assert (
        session.scalars(select(Connection).where(Connection.project_id == project.project_id)).all()
        == []
    )


def test_compatible_cables_are_accepted(session):
    project, _devices, interfaces = _project_with_devices(session, ["PC", "L2_SWITCH"])
    add_connection(
        session,
        project.project_id,
        interface_a_id=interfaces[0],
        interface_b_id=interfaces[1],
        cable_type="STRAIGHT_THROUGH",
    )
    session.commit()
    assert (
        len(
            session.scalars(
                select(Connection).where(Connection.project_id == project.project_id)
            ).all()
        )
        == 1
    )


def test_generic_cable_is_always_accepted(session):
    project, _devices, interfaces = _project_with_devices(session, ["PC", "PC"])
    add_connection(
        session,
        project.project_id,
        interface_a_id=interfaces[0],
        interface_b_id=interfaces[1],
        cable_type="GENERIC_ETHERNET",
    )
    session.commit()
    assert (
        len(
            session.scalars(
                select(Connection).where(Connection.project_id == project.project_id)
            ).all()
        )
        == 1
    )


@pytest.mark.parametrize(
    "address",
    ["224.0.0.1", "127.0.0.1", "169.254.1.1", "192.168.1.0", "192.168.1.255"],
)
def test_invalid_host_address_is_rejected_without_mutation(session, address):
    project, _devices, interfaces = _project_with_devices(session, ["PC"])
    before = project.state_revision

    with pytest.raises(ContractValidationError):
        configure_interface_ipv4(
            session,
            project.project_id,
            interface_id=interfaces[0],
            address=address,
            prefix_length=24,
        )
    session.rollback()

    assert project.state_revision == before
    assert session.get(Interface, interfaces[0]).ipv4_address is None


def test_valid_host_address_is_accepted(session):
    project, _devices, interfaces = _project_with_devices(session, ["PC"])
    configure_interface_ipv4(
        session,
        project.project_id,
        interface_id=interfaces[0],
        address="192.168.10.10",
        prefix_length=24,
    )
    session.commit()
    assert session.get(Interface, interfaces[0]).ipv4_address is not None


def test_limited_broadcast_gateway_is_rejected(session):
    project, devices, _interfaces = _project_with_devices(session, ["PC"])
    before = project.state_revision

    with pytest.raises(ContractValidationError):
        set_host_gateway(
            session,
            project.project_id,
            device_id=devices[0].device_id,
            gateway_ipv4="255.255.255.255",
        )
    session.rollback()

    assert project.state_revision == before
    assert session.get(type(devices[0]), devices[0].device_id).default_gateway_ipv4 is None


def test_excluded_next_hop_is_rejected_and_default_route_stays_valid(session):
    project, devices, _interfaces = _project_with_devices(session, ["ROUTER"])
    router_id = devices[0].device_id
    before = project.state_revision

    with pytest.raises(ContractValidationError):
        add_static_route(
            session,
            project.project_id,
            router_device_id=router_id,
            destination_network="0.0.0.0",
            prefix_length=0,
            next_hop_ipv4="169.254.1.1",
        )
    session.rollback()

    assert project.state_revision == before
    assert (
        session.scalars(
            select(StaticRoute).where(StaticRoute.project_id == project.project_id)
        ).all()
        == []
    )

    add_static_route(
        session,
        project.project_id,
        router_device_id=router_id,
        destination_network="0.0.0.0",
        prefix_length=0,
        next_hop_ipv4="192.168.10.2",
    )
    session.commit()
    assert (
        len(
            session.scalars(
                select(StaticRoute).where(StaticRoute.project_id == project.project_id)
            ).all()
        )
        == 1
    )


def test_excluded_next_hop_is_rejected_on_route_edit(session):
    project, devices, _interfaces = _project_with_devices(session, ["ROUTER"])
    router_id = devices[0].device_id
    add_static_route(
        session,
        project.project_id,
        router_device_id=router_id,
        destination_network="0.0.0.0",
        prefix_length=0,
        next_hop_ipv4="192.168.10.2",
    )
    session.commit()
    route = session.scalars(
        select(StaticRoute).where(StaticRoute.project_id == project.project_id)
    ).one()
    original_next_hop = route.next_hop_ipv4
    before = project.state_revision

    with pytest.raises(ContractValidationError):
        edit_static_route(
            session,
            project.project_id,
            route_id=route.route_id,
            next_hop_ipv4="127.0.0.1",
        )
    session.rollback()

    assert project.state_revision == before
    assert session.get(StaticRoute, route.route_id).next_hop_ipv4 == original_next_hop
