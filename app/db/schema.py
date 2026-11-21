"""PostgreSQL schema materialisation for the TASK-06 persistence layer.

Two artefacts make up the schema:

``Base.metadata``
    Tables, columns, primary/foreign keys, unique/check constraints and the
    canonical PostgreSQL enum types.

``sql/constraints.sql``
    Cross-row invariants that cannot be expressed with a plain constraint
    (immutability guards, interface occupancy, Ping endpoint eligibility,
    revision gaplessness, canonical-JSON hash verification), the ``updated_at``
    triggers, the default retention policy row and the read views.

Both are applied inside one transaction so a partial schema can never be
observed by an application process.
"""

from __future__ import annotations

from importlib import resources

from sqlalchemy import Connection, text

from app.db.base import Base
from app.db.models import (  # noqa: F401  (registers every mapped class)
    ActionLog,
    Checkpoint,
    Device,
    ErrorEnvelope,
    ErrorLog,
    Interface,
    PingLog,
    PingTestCommand,
    PingTestResult,
    Project,
    ProjectRevision,
    ProjectTombstone,
    RetentionPolicy,
    SnapshotRef,
    StaticRoute,
)

SQL_DIRECTORY = "app.db.sql"
CONSTRAINTS_FILE = "constraints.sql"


def load_constraints_sql() -> str:
    """Return the packaged integrity script exactly as shipped."""
    return resources.files(SQL_DIRECTORY).joinpath(CONSTRAINTS_FILE).read_text(encoding="utf-8")


def create_schema(bind: Connection | object) -> None:
    """Create every table, then apply the integrity script.

    ``bind`` is an SQLAlchemy ``Engine`` or ``Connection``.  When an engine is
    supplied a single transaction owns the whole DDL batch.
    """
    engine = bind.engine if hasattr(bind, "engine") else bind  # type: ignore[union-attr]
    script = load_constraints_sql()
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(text(script))


def drop_schema(bind: Connection | object) -> None:
    """Drop every table and the enum types created by :func:`create_schema`."""
    engine = bind.engine if hasattr(bind, "engine") else bind  # type: ignore[union-attr]
    with engine.begin() as connection:
        connection.execute(text("DROP VIEW IF EXISTS v_ping_warning"))
        connection.execute(text("DROP VIEW IF EXISTS v_ping_hop"))
        connection.execute(text("DROP VIEW IF EXISTS v_ping_diagnostic"))
        connection.execute(text("DROP VIEW IF EXISTS v_ping_event"))
        Base.metadata.drop_all(connection)
        for enum_type in sorted(
            {
                column.type.name
                for table in Base.metadata.tables.values()
                for column in table.columns
                if getattr(column.type, "native_enum", False) and getattr(column.type, "name", None)
            }
        ):
            connection.execute(text(f'DROP TYPE IF EXISTS "{enum_type}" CASCADE'))
