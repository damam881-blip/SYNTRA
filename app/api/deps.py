"""Request-scoped database session dependency (TASK-07 §14.2 step 3).

The application lifespan creates one engine and one session factory; every
request borrows a single ``Session`` from that factory and reuses the existing
TASK-06 transaction policy: commit once on success, roll back on any exception,
always close. Service functions never commit independently.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.session import session_scope


def get_db_session(request: Request) -> Iterator[Session]:
    """Yield one session per request using the shared transaction policy."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise RuntimeError("database session factory is not configured")
    with session_scope(factory) as session:
        yield session
