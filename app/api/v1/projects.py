"""Project endpoints (§6, §7.1): create, open, delete, checkpoint save.

Collection reads (``GET /projects``, revisions, checkpoint list) are query
projections and arrive in step 6. ``If-Match`` enforcement arrives in step 5.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import (
    canonical_response,
    checkpoint_receipt,
    deletion_receipt,
    meta_for,
    project_etag,
)
from app.api.v1.revision import require_if_match
from app.api.v1.schemas import (
    CheckpointCreateRequest,
    CheckpointReceiptEnvelope,
    DeleteProjectRequest,
    DeletionReceiptEnvelope,
    ProjectCreateRequest,
    ProjectEnvelope,
    UUIDv7,
)
from app.db.models import Project
from app.modules.projects import service

router = APIRouter(tags=["Projects"])


@router.post(
    "/projects",
    status_code=201,
    response_model=ProjectEnvelope,
    operation_id="createProject",
)
def create_project_endpoint(
    payload: ProjectCreateRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    project = service.create_project(session, name=payload.name, description=payload.description)
    return canonical_response(session, project.project_id, request, response)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectEnvelope,
    operation_id="openProject",
)
def open_project_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    return canonical_response(session, project_id, request, response)


@router.delete(
    "/projects/{project_id}",
    response_model=DeletionReceiptEnvelope,
    operation_id="deleteProject",
)
def delete_project_endpoint(
    project_id: UUIDv7,
    payload: DeleteProjectRequest,
    request: Request,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DeletionReceiptEnvelope:
    tombstone = service.delete_project(session, project_id, confirm_name=payload.confirm_name)
    return DeletionReceiptEnvelope(data=deletion_receipt(tombstone), meta=meta_for(request))


@router.post(
    "/projects/{project_id}/checkpoints",
    status_code=201,
    response_model=CheckpointReceiptEnvelope,
    operation_id="saveCheckpoint",
)
def save_checkpoint_endpoint(
    project_id: UUIDv7,
    payload: CheckpointCreateRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CheckpointReceiptEnvelope:
    checkpoint = service.save_project(session, project_id, label=payload.label)
    # Saving a checkpoint never advances revisions, so the ETag is unchanged.
    response.headers["ETag"] = project_etag(project_id, checkpoint.revision)
    return CheckpointReceiptEnvelope(data=checkpoint_receipt(checkpoint), meta=meta_for(request))
