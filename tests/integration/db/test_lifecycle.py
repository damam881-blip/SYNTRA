"""Project lifecycle and document retrieval tests for TASK-06."""

from __future__ import annotations

import pytest

from app.db.document import configuration_digest
from app.db.errors import DeletionConfirmationError
from app.db.models import ProjectTombstone
from app.modules.projects.service import (
    add_device,
    create_project,
    delete_project,
    list_revisions,
    open_project,
    save_project,
)


def test_create_project_commits_revision_one(session):
    project = create_project(session, name="Lab 1", description="first")
    session.commit()
    assert project.state_revision == 1
    assert project.simulation_revision == 1
    revisions = list_revisions(session, project.project_id)
    assert [(r.revision, r.change_class) for r in revisions] == [(1, "TOPOLOGY")]


def test_open_project_returns_canonical_document(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    doc = open_project(session, project.project_id)
    assert doc["project"]["project_id"] == str(project.project_id)
    assert doc["schema_version"] == "1.0.0"


def test_save_project_creates_checkpoint_without_revision(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    checkpoint = save_project(session, project.project_id, label="v1")
    session.commit()
    assert checkpoint.revision == 1
    doc = open_project(session, project.project_id)
    assert len(doc.get("checkpoints", [])) == 1
    assert list_revisions(session, project.project_id).__len__() == 1


def test_delete_project_requires_confirmation(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    with pytest.raises(DeletionConfirmationError):
        delete_project(session, project.project_id, confirm_name="wrong")
    session.rollback()
    assert session.get(type(project), project.project_id) is not None


def test_delete_project_purges_and_writes_tombstone(session):
    project = create_project(session, name="Lab 1")
    session.commit()
    tombstone = delete_project(session, project.project_id, confirm_name="Lab 1")
    session.commit()
    assert tombstone.project_name == "Lab 1"
    assert session.get(type(project), project.project_id) is None
    assert session.get(ProjectTombstone, project.project_id) is not None


def test_snapshot_capture_freezes_digest(session):
    project = create_project(session, name="Lab 1")
    add_device(session, project.project_id, kind="PC", display_name="PC1")
    session.commit()
    from app.db.document import project_document
    from app.db.snapshot import capture_snapshot

    doc_before = project_document(session, project.project_id)
    digest_before = configuration_digest(doc_before)
    snapshot = capture_snapshot(session, project.project_id)
    session.commit()
    assert snapshot.configuration_digest == digest_before
    # change topology afterwards; snapshot must remain frozen
    add_device(session, project.project_id, kind="PC", display_name="PC2")
    session.commit()
    assert snapshot.configuration_digest == digest_before
