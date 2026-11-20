"""PostgreSQL-backed integration fixtures for TASK-06.

The suite is skipped automatically when the optional ``testing`` extra
(``pgserver``, ``pglast``) is not installed, so the default unit-test run
stays unchanged.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

pgserver = pytest.importorskip("pgserver")  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.schema import create_schema, drop_schema  # noqa: E402


@pytest.fixture(scope="session")
def pg_engine():
    pgdata = pathlib.Path(tempfile.mkdtemp(prefix="syntra-test-")) / "data"
    server = pgserver.get_server(pgdata, cleanup_mode="delete")
    engine = create_engine(server.get_uri(), future=True)
    try:
        yield engine
    finally:
        engine.dispose()
        server.cleanup()


@pytest.fixture
def clean_engine(pg_engine):
    """Drop and recreate the schema for one test, returning a fresh engine."""
    drop_schema(pg_engine)
    create_schema(pg_engine)
    return pg_engine


@pytest.fixture
def session(clean_engine):
    factory = sessionmaker(bind=clean_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
