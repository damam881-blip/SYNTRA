"""Connection (UI "link") endpoints (§6, §7.4).

The backend allocates ``connection_id`` and ``connection_sequence``; the
request carries only the two interface IDs and the cable type.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import canonical_response
from app.api.v1.revision import require_if_match
from app.api.v1.schemas import ConnectionCreateRequest, ProjectEnvelope, UUIDv7
from app.db.models import Project
from app.modules.projects import service

router = APIRouter(prefix="/projects/{project_id}/connections", tags=["Connections"])


@router.post(
    "",
    status_code=201,
    response_model=ProjectEnvelope,
    operation_id="addConnection",
)
def add_connection_endpoint(
    project_id: UUIDv7,
    payload: ConnectionCreateRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.add_connection(
        session,
        project_id,
        interface_a_id=payload.interface_a_id,
        interface_b_id=payload.interface_b_id,
        cable_type=payload.cable_type,
    )
    return canonical_response(session, project_id, request, response)


@router.delete(
    "/{connection_id}",
    response_model=ProjectEnvelope,
    operation_id="removeConnection",
)
def remove_connection_endpoint(
    project_id: UUIDv7,
    connection_id: UUIDv7,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.remove_connection(session, project_id, connection_id=connection_id)
    return canonical_response(session, project_id, request, response)
