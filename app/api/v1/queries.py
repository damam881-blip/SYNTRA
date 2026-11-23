"""Read-only query projections (TASK-07 §14.2 step 6, §6 catalogue).

Canonical state reads reuse ``open_project`` so every collection is observed
at one committed revision; only the project list is a new bounded query
(D7-07). Reads never require ``If-Match`` and never mutate anything.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import meta_for, project_etag
from app.api.v1.schemas import (
    CollectionEnvelope,
    DeviceEnvelope,
    ProjectListEnvelope,
    ProjectSummary,
    UUIDv7,
)
from app.core.exceptions import AppError
from app.db.document import iso_timestamp
from app.db.models import Project
from app.modules.projects import service


class ResourceNotFoundError(AppError):
    """A child lookup found no such resource in this project (§9.2: 404)."""

    code = "NOT_FOUND"
    http_status = 404
    default_message = "Resource does not exist in this project"


router = APIRouter(tags=["Queries"])


def _summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        state_revision=project.state_revision,
        simulation_revision=project.simulation_revision,
        created_at=iso_timestamp(project.created_at),
        updated_at=iso_timestamp(project.updated_at),
    )


def _collection(
    session: Session,
    project_id: UUIDv7,
    key: str,
    request: Request,
    response: Response,
) -> CollectionEnvelope:
    document = service.open_project(session, project_id)
    response.headers["ETag"] = project_etag(project_id, document["project"]["state_revision"])
    return CollectionEnvelope(data=document.get(key, []), meta=meta_for(request))


@router.get(
    "/projects",
    response_model=ProjectListEnvelope,
    operation_id="listProjects",
)
def list_projects_endpoint(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListEnvelope:
    projects = service.list_projects(session, limit=limit, offset=offset)
    return ProjectListEnvelope(
        data=[_summary(project) for project in projects], meta=meta_for(request)
    )


@router.get(
    "/projects/{project_id}/revisions",
    response_model=CollectionEnvelope,
    operation_id="listRevisions",
)
def list_revisions_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> CollectionEnvelope:
    return _collection(session, project_id, "revisions", request, response)


@router.get(
    "/projects/{project_id}/checkpoints",
    response_model=CollectionEnvelope,
    operation_id="listCheckpoints",
)
def list_checkpoints_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> CollectionEnvelope:
    return _collection(session, project_id, "checkpoints", request, response)


@router.get(
    "/projects/{project_id}/devices",
    response_model=CollectionEnvelope,
    operation_id="listDevices",
)
def list_devices_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> CollectionEnvelope:
    return _collection(session, project_id, "devices", request, response)


@router.get(
    "/projects/{project_id}/devices/{device_id}",
    response_model=DeviceEnvelope,
    operation_id="getDevice",
)
def get_device_endpoint(
    project_id: UUIDv7,
    device_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> DeviceEnvelope:
    document = service.open_project(session, project_id)
    response.headers["ETag"] = project_etag(project_id, document["project"]["state_revision"])
    for device in document["devices"]:
        if device["device_id"] == str(device_id):
            return DeviceEnvelope(data=device, meta=meta_for(request))
    raise ResourceNotFoundError(f"device {device_id} does not exist in project {project_id}")


@router.get(
    "/projects/{project_id}/interfaces",
    response_model=CollectionEnvelope,
    operation_id="listInterfaces",
)
def list_interfaces_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> CollectionEnvelope:
    return _collection(session, project_id, "interfaces", request, response)


@router.get(
    "/projects/{project_id}/connections",
    response_model=CollectionEnvelope,
    operation_id="listConnections",
)
def list_connections_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> CollectionEnvelope:
    return _collection(session, project_id, "connections", request, response)


@router.get(
    "/projects/{project_id}/static-routes",
    response_model=CollectionEnvelope,
    operation_id="listStaticRoutes",
)
def list_static_routes_endpoint(
    project_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> CollectionEnvelope:
    return _collection(session, project_id, "static_routes", request, response)
