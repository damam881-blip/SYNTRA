"""Import all mapped classes so ``Base.metadata`` is complete."""

from app.db.models.audit import ProjectTombstone
from app.db.models.logs import ActionLog, ErrorLog, PingLog, RetentionPolicy
from app.db.models.simulation import (
    ErrorEnvelope,
    PingTestCommand,
    PingTestResult,
    SnapshotRef,
)
from app.db.models.topology import (
    Checkpoint,
    Connection,
    Device,
    Interface,
    Project,
    ProjectRevision,
    StaticRoute,
)

__all__ = [
    "ActionLog",
    "Checkpoint",
    "Connection",
    "Device",
    "ErrorEnvelope",
    "ErrorLog",
    "Interface",
    "PingLog",
    "PingTestCommand",
    "PingTestResult",
    "Project",
    "ProjectRevision",
    "ProjectTombstone",
    "RetentionPolicy",
    "SnapshotRef",
    "StaticRoute",
]
