"""Static-route endpoints (§6, §7.5).

``route_id`` and ``route_sequence`` are backend-generated. The route model has
no metric or exit-interface field, so neither appears in any payload.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import canonical_response
from app.api.v1.revision import require_if_match
from app.api.v1.schemas import (
    ProjectEnvelope,
    StaticRouteCreateRequest,
    StaticRoutePatchRequest,
    UUIDv7,
)
from app.db.models import Project
from app.modules.projects import service

router = APIRouter(prefix="/projects/{project_id}/static-routes", tags=["Static Routes"])


@router.post(
    "",
    status_code=201,
    response_model=ProjectEnvelope,
    operation_id="addStaticRoute",
)
def add_static_route_endpoint(
    project_id: UUIDv7,
    payload: StaticRouteCreateRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.add_static_route(
        session,
        project_id,
        router_device_id=payload.router_device_id,
        destination_network=payload.destination_network,
        prefix_length=payload.prefix_length,
        next_hop_ipv4=payload.next_hop_ipv4,
    )
    return canonical_response(session, project_id, request, response)


@router.patch(
    "/{route_id}",
    response_model=ProjectEnvelope,
    operation_id="editStaticRoute",
)
def edit_static_route_endpoint(
    project_id: UUIDv7,
    route_id: UUIDv7,
    payload: StaticRoutePatchRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.edit_static_route(
        session,
        project_id,
        route_id=route_id,
        destination_network=payload.destination_network,
        prefix_length=payload.prefix_length,
        next_hop_ipv4=payload.next_hop_ipv4,
    )
    return canonical_response(session, project_id, request, response)


@router.delete(
    "/{route_id}",
    response_model=ProjectEnvelope,
    operation_id="deleteStaticRoute",
)
def delete_static_route_endpoint(
    project_id: UUIDv7,
    route_id: UUIDv7,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.delete_static_route(session, project_id, route_id=route_id)
    return canonical_response(session, project_id, request, response)
