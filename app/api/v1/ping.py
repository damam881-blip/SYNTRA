"""Ping test adapter (TASK-07 §14.2 step 7).

The endpoint owns command acceptance, snapshot capture, synchronous simulation
through the approved ``PingRunner`` port and immutable result persistence. The
engine itself stays pure and performs none of those steps.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import project_etag
from app.api.v1.revision import require_if_match
from app.api.v1.schemas import ApiMeta, PingCreateRequest, PingEnvelope, UUIDv7
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.errors import ContractValidationError, PreconditionConflictError
from app.db.models import PingTestCommand, Project, SnapshotRef
from app.db.snapshot import replay_input
from app.engine.ping import InvalidReplayInputError, SimulatedPingRunner
from app.modules.logs import service as logs_service
from app.modules.projects import service as project_service

router = APIRouter(prefix="/projects/{project_id}/ping-tests", tags=["Ping"])


def _result_document(row: object) -> dict[str, object]:
    return json.loads(row.canonical_json)  # type: ignore[attr-defined]


@router.post(
    "",
    status_code=201,
    response_model=PingEnvelope,
    operation_id="createPingTest",
)
def create_ping_test_endpoint(
    project_id: UUIDv7,
    payload: PingCreateRequest,
    request: Request,
    response: Response,
    guarded: Annotated[Project, Depends(require_if_match)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PingEnvelope:
    existing = None
    try:
        existing = logs_service.get_ping_result(session, payload.test_id)
    except (ValueError, LookupError):
        existing = None
    if existing is not None:
        if (
            existing.project_id != project_id
            or existing.source_device_id != payload.source_device_id
            or existing.destination_device_id != payload.destination_device_id
        ):
            raise ConflictError(
                "test_id reuse conflicts with the accepted command",
                code="TEST_ID_REUSE_CONFLICT",
            )
        snapshot_row = session.get(SnapshotRef, existing.snapshot_id)
        if snapshot_row is None:
            raise NotFoundError("snapshot referenced by the Ping result does not exist")
        project = project_service.open_project(session, project_id)
        result_document = _result_document(existing)
        response.status_code = 200
        response.headers["ETag"] = project_etag(project_id, project["project"]["state_revision"])
        meta = ApiMeta.for_ping(
            base_simulation_revision=snapshot_row.base_simulation_revision,
            current_simulation_revision=project["project"]["simulation_revision"],
            request_id=getattr(request.state, "request_id", None),
            command_id=payload.test_id,
        )
        return PingEnvelope(data=result_document, meta=meta)

    accepted_command = session.scalars(
        select(PingTestCommand).where(PingTestCommand.test_id == payload.test_id)
    ).one_or_none()
    if accepted_command is not None:
        if (
            accepted_command.project_id != project_id
            or accepted_command.source_device_id != payload.source_device_id
            or accepted_command.destination_device_id != payload.destination_device_id
        ):
            raise ConflictError(
                "test_id reuse conflicts with the accepted command",
                code="TEST_ID_REUSE_CONFLICT",
            )
        raise ConflictError(
            "the Ping command is already accepted and has no recorded result",
            code="PING_IN_PROGRESS",
        )

    try:
        command = logs_service.accept_ping_command(
            session,
            project_id,
            source_device_id=payload.source_device_id,
            destination_device_id=payload.destination_device_id,
            test_id=payload.test_id,
        )
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except (ValueError, ContractValidationError) as exc:
        raise ValidationError(str(exc)) from exc
    except IntegrityError as exc:
        if "test_id" not in str(exc).lower():
            raise
        raise ConflictError(
            "test_id conflicts with an already accepted Ping command",
            code="TEST_ID_REUSE_CONFLICT",
        ) from exc

    snapshot_row = session.get(SnapshotRef, command.snapshot_id)
    if snapshot_row is None:
        raise NotFoundError("snapshot referenced by the Ping command does not exist")
    try:
        replay = replay_input(snapshot_row)
    except InvalidReplayInputError as exc:
        raise ValidationError(str(exc)) from exc
    result = SimulatedPingRunner().run(
        replay,
        test_id=command.test_id,
        project_id=project_id,
        source_device_id=command.source_device_id,
        destination_device_id=command.destination_device_id,
    )
    try:
        row = logs_service.record_ping_result(session, result)
    except PreconditionConflictError as exc:
        raise ConflictError(str(exc), code="TEST_ID_REUSE_CONFLICT") from exc

    project = project_service.open_project(session, project_id)
    response.headers["ETag"] = project_etag(project_id, project["project"]["state_revision"])
    response.headers["Location"] = f"/api/v1/projects/{project_id}/ping-tests/{command.test_id}"

    meta = ApiMeta.for_ping(
        base_simulation_revision=snapshot_row.base_simulation_revision,
        current_simulation_revision=project["project"]["simulation_revision"],
        request_id=getattr(request.state, "request_id", None),
        command_id=command.test_id,
    )
    return PingEnvelope(data=_result_document(row), meta=meta)


@router.get(
    "/{test_id}",
    response_model=PingEnvelope,
    operation_id="getPingTest",
)
def get_ping_test_endpoint(
    project_id: UUIDv7,
    test_id: UUIDv7,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> PingEnvelope:
    try:
        row = logs_service.get_ping_result(session, test_id)
    except (ValueError, LookupError) as exc:
        raise NotFoundError(f"Ping result {test_id} does not exist") from exc
    if row.project_id != project_id:
        raise NotFoundError(f"Ping result {test_id} does not exist in project {project_id}")
    try:
        project = project_service.open_project(session, project_id)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    snapshot_row = session.get(SnapshotRef, row.snapshot_id)
    if snapshot_row is None:
        raise NotFoundError("snapshot referenced by the Ping result does not exist")
    response.headers["ETag"] = project_etag(project_id, project["project"]["state_revision"])

    meta = ApiMeta.for_ping(
        base_simulation_revision=snapshot_row.base_simulation_revision,
        current_simulation_revision=project["project"]["simulation_revision"],
        request_id=getattr(request.state, "request_id", None),
        command_id=test_id,
    )
    return PingEnvelope(data=_result_document(row), meta=meta)
