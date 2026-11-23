"""Device and host-gateway endpoints (§6, §7.2, §7.3).

Each PATCH targets one logical mutation so the service advances
``state_revision`` exactly once per call. The default gateway belongs to the
PC/Server device, never to an interface or a router.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import canonical_response
from app.api.v1.revision import require_if_match
from app.api.v1.schemas import (
    DeviceCreateRequest,
    DevicePositionRequest,
    DeviceRenameRequest,
    GatewayRequest,
    ProjectEnvelope,
    RotationRequest,
    UUIDv7,
)
from app.db.models import Project
from app.modules.projects import service
from app.modules.projects.service import Position

router = APIRouter(prefix="/projects/{project_id}/devices", tags=["Devices"])


@router.post(
    "",
    status_code=201,
    response_model=ProjectEnvelope,
    operation_id="addDevice",
)
def add_device_endpoint(
    project_id: UUIDv7,
    payload: DeviceCreateRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    position = (
        Position(x=payload.position.x, y=payload.position.y, z=payload.position.z)
        if payload.position is not None
        else None
    )
    service.add_device(
        session,
        project_id,
        kind=payload.kind,
        display_name=payload.display_name,
        position=position,
        rotation_y_degrees=payload.rotation_y_degrees,
    )
    return canonical_response(session, project_id, request, response)


@router.patch(
    "/{device_id}/name",
    response_model=ProjectEnvelope,
    operation_id="renameDevice",
)
def rename_device_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    payload: DeviceRenameRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.rename_device(
        session, project_id, device_id=device_id, display_name=payload.display_name
    )
    return canonical_response(session, project_id, request, response)


@router.patch(
    "/{device_id}/position",
    response_model=ProjectEnvelope,
    operation_id="moveDevice",
)
def move_device_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    payload: DevicePositionRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.move_device(
        session,
        project_id,
        device_id=device_id,
        position=Position(x=payload.position.x, y=payload.position.y, z=payload.position.z),
    )
    return canonical_response(session, project_id, request, response)


@router.patch(
    "/{device_id}/rotation",
    response_model=ProjectEnvelope,
    operation_id="rotateDevice",
)
def rotate_device_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    payload: RotationRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.rotate_device(
        session,
        project_id,
        device_id=device_id,
        rotation_y_degrees=payload.rotation_y_degrees,
    )
    return canonical_response(session, project_id, request, response)


@router.delete(
    "/{device_id}",
    response_model=ProjectEnvelope,
    operation_id="removeDevice",
)
def remove_device_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.remove_device(session, project_id, device_id=device_id)
    return canonical_response(session, project_id, request, response)


@router.put(
    "/{device_id}/default-gateway",
    response_model=ProjectEnvelope,
    operation_id="setHostGateway",
)
def set_host_gateway_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    payload: GatewayRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.set_host_gateway(
        session, project_id, device_id=device_id, gateway_ipv4=payload.gateway_ipv4
    )
    return canonical_response(session, project_id, request, response)


@router.delete(
    "/{device_id}/default-gateway",
    response_model=ProjectEnvelope,
    operation_id="clearHostGateway",
)
def clear_host_gateway_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProjectEnvelope:
    service.clear_host_gateway(session, project_id, device_id=device_id)
    return canonical_response(session, project_id, request, response)
