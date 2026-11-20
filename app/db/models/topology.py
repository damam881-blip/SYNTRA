"""TASK-04 topology and configuration persistence models.
The relational shape mirrors the approved TASK-04 v1.0.0 logical model.  The
canonical document remains the interchange/snapshot form; these tables are the
committed project aggregate.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, IPv4UInt32, positive_check, uuid7_check
from app.db.enums import AdminState, CableType, ChangeClass, DeviceKind, InterfaceKind
from app.db.pgtypes import (
    ADMIN_STATE,
    CABLE_TYPE,
    CHANGE_CLASS,
    DEVICE_KIND,
    INTERFACE_KIND,
)
class Project(Base):
    __tablename__ = "project"
    project_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    state_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    simulation_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1
    )
    next_device_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1
    )
    next_mac_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    next_connection_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    devices: Mapped[list[Device]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    interfaces: Mapped[list[Interface]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    connections: Mapped[list[Connection]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    static_routes: Mapped[list[StaticRoute]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    revisions: Mapped[list[ProjectRevision]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    checkpoints: Mapped[list[Checkpoint]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    __table_args__ = (
        uuid7_check("project_id", "project_id_uuid7"),
        positive_check("state_revision", "state_revision_positive"),
        positive_check("simulation_revision", "simulation_revision_positive"),
        CheckConstraint(
            "simulation_revision <= state_revision",
            name="simulation_revision_not_ahead",
        ),
        positive_check("next_device_sequence", "next_device_sequence_positive"),
        positive_check("next_mac_sequence", "next_mac_sequence_positive"),
        positive_check(
            "next_connection_sequence", "next_connection_sequence_positive"
        ),
        CheckConstraint(
            "length(btrim(name)) > 0", name="name_not_blank"
        ),
    )
class ProjectRevision(Base):
    __tablename__ = "project_revision"
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_class: Mapped[ChangeClass] = mapped_column(
        CHANGE_CLASS, nullable=False
    )
    change_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False
    )
    affected_entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="revisions")
    __table_args__ = (
        positive_check("revision", "revision_positive"),
        CheckConstraint(
            "array_length(change_kinds, 1) >= 1", name="change_kinds_not_empty"
        ),
        CheckConstraint(
            "change_kinds <@ ARRAY["
            "'PROJECT_CREATED','DEVICE_ADDED','DEVICE_REMOVED','DEVICE_RENAMED',"
            "'DEVICE_MOVED','INTERFACE_ADMIN_STATE_CHANGED',"
            "'INTERFACE_IPV4_CONFIGURED','INTERFACE_IPV4_CLEARED',"
            "'HOST_GATEWAY_CONFIGURED','HOST_GATEWAY_CLEARED',"
            "'CONNECTION_ADDED','CONNECTION_REMOVED','STATIC_ROUTE_ADDED',"
            "'STATIC_ROUTE_EDITED','STATIC_ROUTE_DELETED'"
            "]::varchar[]",
            name="change_kinds_approved",
        ),
    )
class Checkpoint(Base):
    __tablename__ = "checkpoint"
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="checkpoints")
    revision_row: Mapped[ProjectRevision] = relationship(
        primaryjoin=(
            "and_(Checkpoint.project_id == ProjectRevision.project_id, "
            "Checkpoint.revision == ProjectRevision.revision)"
        ),
        foreign_keys="[Checkpoint.project_id, Checkpoint.revision]",
        viewonly=True,
    )
    __table_args__ = (
        uuid7_check("checkpoint_id", "checkpoint_id_uuid7"),
        positive_check("revision", "checkpoint_revision_positive"),
        ForeignKeyConstraint(
            ["project_id", "revision"],
            ["project_revision.project_id", "project_revision.revision"],
            ondelete="CASCADE",
            name="fk_checkpoint_project_revision",
        ),
    )
class Device(Base):
    __tablename__ = "device"
    device_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[DeviceKind] = mapped_column(
        DEVICE_KIND, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    device_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    default_gateway_ipv4: Mapped[int | None] = mapped_column(IPv4UInt32)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_z: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rotation_y_degrees: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    next_route_sequence: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="devices")
    interfaces: Mapped[list[Interface]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
        primaryjoin=(
            "and_(Device.project_id == Interface.project_id, "
            "Device.device_id == Interface.device_id)"
        ),
        foreign_keys="[Interface.project_id, Interface.device_id]",
        overlaps="interfaces,project",
    )
    static_routes: Mapped[list[StaticRoute]] = relationship(
        back_populates="router",
        cascade="all, delete-orphan",
        passive_deletes=True,
        primaryjoin=(
            "and_(Device.project_id == StaticRoute.project_id, "
            "Device.device_id == StaticRoute.router_device_id)"
        ),
        foreign_keys="[StaticRoute.project_id, StaticRoute.router_device_id]",
        overlaps="static_routes,project",
    )
    __table_args__ = (
        uuid7_check("device_id", "device_id_uuid7"),
        UniqueConstraint("project_id", "device_id", name="uq_device_project_device"),
        UniqueConstraint(
            "project_id", "normalized_name", name="uq_device_project_normalized_name"
        ),
        UniqueConstraint(
            "project_id", "device_sequence", name="uq_device_project_sequence"
        ),
        positive_check("device_sequence", "device_sequence_positive"),
        CheckConstraint(
            "length(btrim(display_name)) > 0", name="display_name_not_blank"
        ),
        CheckConstraint(
            "length(normalized_name) > 0", name="normalized_name_not_blank"
        ),
        CheckConstraint(
            "rotation_y_degrees >= -180 AND rotation_y_degrees < 180",
            name="rotation_bounds",
        ),
        CheckConstraint(
            "(kind = 'ROUTER' AND next_route_sequence IS NOT NULL) "
            "OR (kind <> 'ROUTER' AND next_route_sequence IS NULL)",
            name="route_counter_router_only",
        ),
        CheckConstraint(
            "next_route_sequence IS NULL OR next_route_sequence >= 1",
            name="route_counter_positive",
        ),
    )
class Interface(Base):
    __tablename__ = "interface"
    interface_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    interface_kind: Mapped[InterfaceKind] = mapped_column(
        INTERFACE_KIND, nullable=False
    )
    admin_state: Mapped[AdminState] = mapped_column(
        ADMIN_STATE, nullable=False
    )
    mac_address: Mapped[str] = mapped_column(String(17), nullable=False)
    mac_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ipv4_address: Mapped[int | None] = mapped_column(IPv4UInt32)
    ipv4_prefix_length: Mapped[int | None] = mapped_column(SmallInteger)
    project: Mapped[Project] = relationship(back_populates="interfaces")
    device: Mapped[Device] = relationship(
        back_populates="interfaces",
        primaryjoin=(
            "and_(Interface.project_id == Device.project_id, "
            "Interface.device_id == Device.device_id)"
        ),
        foreign_keys="[Interface.project_id, Interface.device_id]",
        overlaps="interfaces,project",
    )
    __table_args__ = (
        uuid7_check("interface_id", "interface_id_uuid7"),
        UniqueConstraint(
            "project_id", "interface_id", name="uq_interface_project_interface"
        ),
        UniqueConstraint(
            "device_id", "ordinal", name="uq_interface_device_ordinal"
        ),
        UniqueConstraint(
            "project_id", "mac_address", name="uq_interface_project_mac"
        ),
        ForeignKeyConstraint(
            ["project_id", "device_id"],
            ["device.project_id", "device.device_id"],
            ondelete="CASCADE",
            name="fk_interface_device_project",
        ),
        positive_check("mac_sequence", "mac_sequence_positive"),
        CheckConstraint("ordinal >= 0 AND ordinal <= 7", name="ordinal_bounds"),
        CheckConstraint(
            "display_name ~ '^(FastEthernet0(/[0-6])?|GigabitEthernet0(/[0-2])?)$'",
            name="display_name_inventory",
        ),
        CheckConstraint(
            "mac_address ~ '^[0-9a-f]{2}(:[0-9a-f]{2}){5}$'",
            name="mac_address_canonical",
        ),
        CheckConstraint(
            "(ipv4_address IS NULL AND ipv4_prefix_length IS NULL) "
            "OR (ipv4_address IS NOT NULL AND ipv4_prefix_length IS NOT NULL)",
            name="ipv4_pair_complete",
        ),
        CheckConstraint(
            "ipv4_prefix_length IS NULL "
            "OR (ipv4_prefix_length >= 1 AND ipv4_prefix_length <= 30)",
            name="ipv4_prefix_bounds",
        ),
        CheckConstraint(
            "ipv4_address IS NULL OR (ipv4_address >= 0 AND ipv4_address <= 4294967295)",
            name="ipv4_uint32",
        ),
    )
class Connection(Base):
    __tablename__ = "connection"
    connection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False
    )
    interface_a_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    interface_b_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cable_type: Mapped[CableType] = mapped_column(
        CABLE_TYPE, nullable=False
    )
    connection_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="connections")
    interface_a: Mapped[Interface] = relationship(
        primaryjoin=(
            "and_(Connection.project_id == Interface.project_id, "
            "Connection.interface_a_id == Interface.interface_id)"
        ),
        foreign_keys="[Connection.project_id, Connection.interface_a_id]",
        viewonly=True,
    )
    interface_b: Mapped[Interface] = relationship(
        primaryjoin=(
            "and_(Connection.project_id == Interface.project_id, "
            "Connection.interface_b_id == Interface.interface_id)"
        ),
        foreign_keys="[Connection.project_id, Connection.interface_b_id]",
        viewonly=True,
    )
    __table_args__ = (
        uuid7_check("connection_id", "connection_id_uuid7"),
        UniqueConstraint(
            "project_id", "connection_sequence", name="uq_connection_project_sequence"
        ),
        ForeignKeyConstraint(
            ["project_id", "interface_a_id"],
            ["interface.project_id", "interface.interface_id"],
            ondelete="CASCADE",
            name="fk_connection_interface_a",
        ),
        ForeignKeyConstraint(
            ["project_id", "interface_b_id"],
            ["interface.project_id", "interface.interface_id"],
            ondelete="CASCADE",
            name="fk_connection_interface_b",
        ),
        positive_check("connection_sequence", "connection_sequence_positive"),
        CheckConstraint("interface_a_id < interface_b_id", name="endpoints_canonical"),
    )
class StaticRoute(Base):
    __tablename__ = "static_route"
    route_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False
    )
    router_device_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    destination_network: Mapped[int] = mapped_column(IPv4UInt32, nullable=False)
    prefix_length: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    next_hop_ipv4: Mapped[int] = mapped_column(IPv4UInt32, nullable=False)
    route_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="static_routes")
    router: Mapped[Device] = relationship(
        back_populates="static_routes",
        primaryjoin=(
            "and_(StaticRoute.project_id == Device.project_id, "
            "StaticRoute.router_device_id == Device.device_id)"
        ),
        foreign_keys="[StaticRoute.project_id, StaticRoute.router_device_id]",
        overlaps="project,static_routes",
    )
    __table_args__ = (
        uuid7_check("route_id", "route_id_uuid7"),
        UniqueConstraint(
            "router_device_id", "route_sequence", name="uq_route_router_sequence"
        ),
        UniqueConstraint(
            "router_device_id",
            "destination_network",
            "prefix_length",
            name="uq_route_destination",
        ),
        ForeignKeyConstraint(
            ["project_id", "router_device_id"],
            ["device.project_id", "device.device_id"],
            ondelete="CASCADE",
            name="fk_route_router_project",
        ),
        positive_check("route_sequence", "route_sequence_positive"),
        CheckConstraint(
            "prefix_length >= 0 AND prefix_length <= 32", name="prefix_bounds"
        ),
        CheckConstraint(
            "destination_network >= 0 AND destination_network <= 4294967295",
            name="destination_uint32",
        ),
        CheckConstraint(
            "next_hop_ipv4 >= 0 AND next_hop_ipv4 <= 4294967295",
            name="next_hop_uint32",
        ),
        CheckConstraint(
            "(destination_network & ((1::bigint << (32 - prefix_length)) - 1)) = 0",
            name="destination_network_aligned",
        ),
    )
