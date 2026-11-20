"""Shared PostgreSQL enum type instances.

Each type is instantiated exactly once so SQLAlchemy emits one ``CREATE TYPE``
per enum even when several tables reference it.
"""

from __future__ import annotations

from app.db.base import pg_enum
from app.db.enums import (
    AdminState,
    AggregateOutcome,
    CableType,
    ChangeClass,
    DeviceKind,
    ErrorClass,
    ErrorReason,
    ExecutionStatus,
    InterfaceKind,
    ObservationStatus,
)

DEVICE_KIND = pg_enum(DeviceKind, "device_kind")
INTERFACE_KIND = pg_enum(InterfaceKind, "interface_kind")
ADMIN_STATE = pg_enum(AdminState, "admin_state")
CABLE_TYPE = pg_enum(CableType, "cable_type")
CHANGE_CLASS = pg_enum(ChangeClass, "change_class")
EXECUTION_STATUS = pg_enum(ExecutionStatus, "execution_status")
AGGREGATE_OUTCOME = pg_enum(AggregateOutcome, "aggregate_outcome")
OBSERVATION_STATUS = pg_enum(ObservationStatus, "observation_status")
ERROR_CLASS = pg_enum(ErrorClass, "error_class")
ERROR_REASON = pg_enum(ErrorReason, "error_reason")
