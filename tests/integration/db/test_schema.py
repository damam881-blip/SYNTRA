"""DDL and metadata assertions for the TASK-06 schema."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.db.base import Base


def test_schema_creates_all_tables(session):
    inspector = sa.inspect(session.bind)
    tables = set(inspector.get_table_names())
    assert "project" in tables
    assert "project_revision" in tables
    assert "snapshot_ref" in tables
    assert "ping_test_result" in tables
    assert "error_envelope" in tables
    assert "project_tombstone" in tables
    assert "retention_policy" in tables
    assert len(Base.metadata.tables) == 16


def test_schema_creates_views(session):
    rows = (
        session.execute(sa.text("select viewname from pg_views where schemaname='public'"))
        .scalars()
        .all()
    )
    assert {"v_ping_event", "v_ping_diagnostic", "v_ping_hop", "v_ping_warning"} <= set(rows)


def test_schema_creates_canonical_enums(session):
    rows = (
        session.execute(sa.text("select typname from pg_type where typtype='e' order by 1"))
        .scalars()
        .all()
    )
    assert "device_kind" in rows
    assert "change_class" in rows
    assert "execution_status" in rows
    assert "error_class" in rows


def test_retention_policy_seed(session):
    row = session.execute(
        sa.text("select policy_name, action_log_retention_days from retention_policy")
    ).one()
    assert row.policy_name == "default"
    assert row.action_log_retention_days == 90


def test_schema_drop_is_clean(pg_engine):
    from app.db.schema import create_schema, drop_schema

    drop_schema(pg_engine)
    inspector = sa.inspect(pg_engine)
    assert "project" not in inspector.get_table_names()
    create_schema(pg_engine)
    assert "project" in sa.inspect(pg_engine).get_table_names()


def test_alembic_upgrade_downgrade_upgrade(pg_engine, monkeypatch):
    """The shipped migration, not just metadata bootstrap, is reversible."""
    from app.db.schema import drop_schema

    root = Path(__file__).resolve().parents[3]
    drop_schema(pg_engine)
    with pg_engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))

    monkeypatch.setenv("SYNTRA_DATABASE_URL", str(pg_engine.url))
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    command.upgrade(config, "head")
    assert "project" in sa.inspect(pg_engine).get_table_names()
    command.downgrade(config, "base")
    assert "project" not in sa.inspect(pg_engine).get_table_names()
    command.upgrade(config, "head")
    assert "project" in sa.inspect(pg_engine).get_table_names()
