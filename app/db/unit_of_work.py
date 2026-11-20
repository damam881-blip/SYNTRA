"""Explicit transaction boundary for project and evidence writes.

TASK-06 requires atomicity: a failed persistence step must leave the previously
committed project state untouched.  Every service function accepts a live
``Session`` and never commits on its own; callers either use
:class:`UnitOfWork` or :func:`app.db.session.session_scope`.

Typical usage::

    with UnitOfWork(factory) as uow:
        create_project(uow.session, name="Lab 1")
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker


class UnitOfWork:
    """Context manager that owns one session and one transaction."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self.session: Session | None = None
        self._committed = False

    def __enter__(self) -> UnitOfWork:
        self.session = self._factory()
        return self

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        self.session.rollback()
        self._committed = False

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if self.session is None:
            return False
        try:
            if exc_type is not None:
                self.session.rollback()
            elif not self._committed:
                self.session.commit()
                self._committed = True
        finally:
            self.session.close()
        return False
