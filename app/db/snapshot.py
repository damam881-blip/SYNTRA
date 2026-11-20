"""Freeze and verify a TASK-04 configuration at one committed revision.

A simulation snapshot is *not* a pointer to mutable current state.  At capture
time the behavioural configuration projection is serialised once, hashed with
SHA-256 and stored verbatim.  TASK-05 results therefore keep referring to the
exact configuration that produced them even after the project changes again.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.base import uuid7
from app.db.document import (
    MODEL_SCHEMA_VERSION,
    canonical_json_bytes,
    configuration_digest,
    configuration_projection,
    lock_project,
    project_document,
)
from app.db.models import Project, SnapshotRef


class SnapshotIntegrityError(ValueError):
    """Raised when stored snapshot bytes and the stored digest disagree."""


def capture_snapshot(
    session: Session,
    project_id: uuid.UUID,
    *,
    project: Project | None = None,
) -> SnapshotRef:
    """Freeze the current configuration and insert its ``snapshot_ref`` row.

    The caller must already be inside a transaction.  ``project`` may be the
    row-locked project fetched by the calling service, avoiding a second query.
    """
    locked = project if project is not None else lock_project(session, project_id)
    document = project_document(session, project_id, consistent_read=False)
    projection = configuration_projection(document)
    canonical = canonical_json_bytes(document)
    digest = configuration_digest(document)

    snapshot = SnapshotRef(
        snapshot_id=uuid7(),
        project_id=locked.project_id,
        base_state_revision=locked.state_revision,
        base_simulation_revision=locked.simulation_revision,
        schema_version=MODEL_SCHEMA_VERSION,
        configuration_digest=digest,
        configuration_json=projection,
        canonical_json=canonical.decode("utf-8"),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def verify_snapshot(snapshot: SnapshotRef) -> None:
    """Recompute the digest from the stored canonical bytes."""
    from hashlib import sha256

    actual = sha256(snapshot.canonical_json.encode("utf-8")).hexdigest()
    if actual != snapshot.configuration_digest:
        raise SnapshotIntegrityError(
            f"snapshot {snapshot.snapshot_id} digest {snapshot.configuration_digest} "
            f"does not match canonical bytes ({actual})"
        )


def replay_input(snapshot: SnapshotRef) -> dict[str, Any]:
    """Return an isolated copy of the frozen configuration projection."""
    verify_snapshot(snapshot)
    return {
        "snapshot_id": str(snapshot.snapshot_id),
        "base_state_revision": snapshot.base_state_revision,
        "base_simulation_revision": snapshot.base_simulation_revision,
        "schema_version": snapshot.schema_version,
        "configuration_digest": snapshot.configuration_digest,
        "configuration": snapshot.configuration_json,
    }
