"""TASK-06 initial schema: tables, canonical enums and integrity triggers.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-20

The DDL is emitted through the same canonical code path used at runtime,
``Base.metadata.create_all`` + ``app/db/sql/constraints.sql``.  A later
migration can then be a normal column-by-column Alembic revision; this first one
cannot retroactively become smaller without breaking existing deployments.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import Base
from app.db.schema import load_constraints_sql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    bind.execute(sa.text(load_constraints_sql()))


def downgrade() -> None:
    bind = op.get_bind()
    for view in ("v_ping_warning", "v_ping_hop", "v_ping_diagnostic", "v_ping_event"):
        bind.execute(sa.text(f"DROP VIEW IF EXISTS {view}"))
    Base.metadata.drop_all(bind)
    for enum_type in sorted(
        {
            column.type.name
            for table in Base.metadata.tables.values()
            for column in table.columns
            if getattr(column.type, "native_enum", False)
            and getattr(column.type, "name", None)
        }
    ):
        bind.execute(sa.text(f'DROP TYPE IF EXISTS "{enum_type}" CASCADE'))
