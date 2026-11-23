"""Interface configuration endpoints (§6, §7.3).

Interfaces are provisioned by device creation; there is no create/delete
interface endpoint. All three operations return the refreshed canonical
project document.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import canonical_response
from app.api.v1.revision import require_if_match
from app.api.v1.schemas import (
    AdminStateRequest,
    InterfaceIPv4Request,
    ProjectEnvelope,
    UUIDv7,
)
from app.db.models import Project
from app.modules.projects import service

router = APIRouter(prefix="/projects/{project_id}/interfaces", tags=["Interfaces"])


@router.patch(
    "/{interface_id}/admin-state",
    response_model=ProjectEnvelope,
    operation_id="setInterfaceAdminState",
)
def set_interface_admin_state_endpoint(
    project_id: UUIDv7,
    interface_id: UUIDv7,
    payload: AdminStateRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.set_interface_admin_state(
        session, project_id, interface_id=interface_id, admin_state=payload.admin_state
    )
    return canonical_response(session, project_id, request, response)


@router.put(
    "/{interface_id}/ipv4",
    response_model=ProjectEnvelope,
    operation_id="configureInterfaceIPv4",
)
def configure_interface_ipv4_endpoint(
    project_id: UUIDv7,
    interface_id: UUIDv7,
    payload: InterfaceIPv4Request,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.configure_interface_ipv4(
        session,
        project_id,
        interface_id=interface_id,
        address=payload.address,
        prefix_length=payload.prefix_length,
    )
    return canonical_response(session, project_id, request, response)


@router.delete(
    "/{interface_id}/ipv4",
    response_model=ProjectEnvelope,
    operation_id="clearInterfaceIPv4",
)
def clear_interface_ipv4_endpoint(
    project_id: UUIDv7,
    interface_id: UUIDv7,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.clear_interface_ipv4(session, project_id, interface_id=interface_id)
    return canonical_response(session, project_id, request, response)
