"""Engine/session configuration for the TASK-06 persistence layer.

Deployment assumption: PostgreSQL >= 13 (tested on 16.2).  The application
connects through psycopg 3.  ``SYNTRA_DATABASE_URL`` is the single supported
configuration point; the default targets a local PostgreSQL instance with the
``postgres`` role, which is the documented developer setup.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5432/syntra"
DATABASE_URL_ENV = "SYNTRA_DATABASE_URL"
ECHO_ENV = "SYNTRA_DB_ECHO"


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def create_db_engine(
    url: str | None = None,
    *,
    echo: bool | None = None,
) -> Engine:
    """Create a pool-backed engine suitable for a long-running process."""
    if echo is None:
        echo = os.environ.get(ECHO_ENV, "").lower() in {"1", "true", "yes"}
    return create_engine(
        url or database_url(),
        echo=echo,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on any exception, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
