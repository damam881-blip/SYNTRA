"""Atomicity and rollback tests for TASK-06."""

from __future__ import annotations

import pytest

from app.db.errors import IntegrityConflictError
from app.modules.projects.service import add_device, create_project, list_revisions


def test_duplicate_device_name_rolls_back_revision(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    before = len(list_revisions(session, project.project_id))
    add_device(session, project.project_id, kind="PC", display_name="PC1")
    session.commit()
    with pytest.raises(IntegrityConflictError):
        add_device(session, project.project_id, kind="PC", display_name="PC1")
        session.flush()
    session.rollback()
    after = len(list_revisions(session, project.project_id))
    assert after == before + 1
    # project state still has the first device
    from app.modules.projects.service import open_project

    doc = open_project(session, project.project_id)
    assert [d["display_name"] for d in doc["devices"]] == ["PC1"]


def test_transaction_rollback_preserves_prior_state(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    try:
        add_device(session, project.project_id, kind="PC", display_name="PC1")
        raise RuntimeError("simulated persistence failure")
    except RuntimeError:
        session.rollback()
    doc = __import__("app.modules.projects.service", fromlist=["open_project"]).open_project(
        session, project.project_id
    )
    assert doc["devices"] == []
    assert doc["project"]["state_revision"] == 1
