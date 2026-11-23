"""TASK-07 §14.2 step 3: application lifespan and request-scoped session."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db_session
from app.main import app


class _RecordingSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")


def _request_with_factory(factory):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_factory=factory)))


def _drive(factory, *, fail: bool = False):
    generator = get_db_session(_request_with_factory(factory))
    session = next(generator)
    if fail:
        with pytest.raises(RuntimeError, match="boom"):
            generator.throw(RuntimeError("boom"))
    else:
        with pytest.raises(StopIteration):
            next(generator)
    return session


def test_lifespan_creates_engine_and_session_factory():
    with TestClient(app) as client:
        assert app.state.db_engine is not None
        assert app.state.session_factory is not None
        assert client.get("/health").status_code == 200


def test_dependency_commits_and_closes_on_success():
    session = _RecordingSession()
    returned = _drive(lambda: session)
    assert returned is session
    assert session.events == ["commit", "close"]


def test_dependency_rolls_back_and_closes_on_error():
    session = _RecordingSession()
    returned = _drive(lambda: session, fail=True)
    assert returned is session
    assert session.events == ["rollback", "close"]


def test_dependency_requires_a_configured_factory():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    generator = get_db_session(request)
    with pytest.raises(RuntimeError, match="not configured"):
        next(generator)
