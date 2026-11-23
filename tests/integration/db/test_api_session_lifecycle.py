"""The request-scoped dependency honours the TASK-06 transaction policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.deps import get_db_session
from app.db.models import Project
from app.db.session import create_session_factory
from app.modules.projects.service import create_project


def _request(factory):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_factory=factory)))


def test_dependency_commits_service_work_on_success(clean_engine):
    factory = create_session_factory(clean_engine)
    generator = get_db_session(_request(factory))
    session = next(generator)
    project = create_project(session, name="Lifecycle Lab")
    project_id = project.project_id

    with pytest.raises(StopIteration):
        next(generator)

    with factory() as check:
        assert check.get(Project, project_id) is not None


def test_dependency_rolls_back_service_work_on_error(clean_engine):
    factory = create_session_factory(clean_engine)
    generator = get_db_session(_request(factory))
    session = next(generator)
    project = create_project(session, name="Rollback Lab")
    project_id = project.project_id

    with pytest.raises(RuntimeError, match="boom"):
        generator.throw(RuntimeError("boom"))

    with factory() as check:
        assert check.get(Project, project_id) is None
