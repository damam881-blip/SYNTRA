"""Shared helpers for the TASK-07 v1 routers (§14.2 step 4).

ETag format follows §5.2: ``"p-{project_id}-s{state_revision}"``. The revision
guard that compares ``If-Match`` against the locked row arrives in step 5;
this module only produces the header value and the canonical response shape.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    ApiMeta,
    CheckpointReceipt,
    DeletionReceipt,
    ProjectEnvelope,
)
from app.db.document import iso_timestamp
from app.db.models import Checkpoint, ProjectTombstone
from app.modules.projects.service import open_project


def project_etag(project_id: UUID | str, state_revision: int) -> str:
    """Render the strong ETag for one committed project revision (§5.2)."""
    return f'"p-{project_id}-s{state_revision}"'


def meta_for(request: Request) -> ApiMeta:
    """Envelope metadata carrying the middleware-assigned request ID."""
    return ApiMeta(request_id=getattr(request.state, "request_id", None))


def canonical_response(
    session: Session,
    project_id: UUID,
    request: Request,
    response: Response,
) -> ProjectEnvelope:
    """Return the refreshed canonical document plus its new ETag.

    Called inside the same request transaction as the mutation, so the
    document reflects exactly the state that is about to be committed.
    """
    document = open_project(session, project_id)
    response.headers["ETag"] = project_etag(project_id, document["project"]["state_revision"])
    return ProjectEnvelope(data=document, meta=meta_for(request))


def checkpoint_receipt(checkpoint: Checkpoint) -> CheckpointReceipt:
    """Serialize a saved checkpoint into its dedicated receipt DTO."""
    return CheckpointReceipt(
        checkpoint_id=checkpoint.checkpoint_id,
        project_id=checkpoint.project_id,
        revision=checkpoint.revision,
        label=checkpoint.label,
        created_at=iso_timestamp(checkpoint.created_at),
    )


def deletion_receipt(tombstone: ProjectTombstone) -> DeletionReceipt:
    """Serialize the surviving tombstone into the deletion receipt DTO."""
    return DeletionReceipt(
        project_id=tombstone.project_id,
        project_name=tombstone.project_name,
        last_state_revision=tombstone.last_state_revision,
        last_simulation_revision=tombstone.last_simulation_revision,
        deleted_by=tombstone.deleted_by,
        deleted_at=iso_timestamp(tombstone.deleted_at),
    )
