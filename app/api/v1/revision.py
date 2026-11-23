"""If-Match revision guard (TASK-07 §5.2, §14.2 step 5, decision D7-02).

Every project-scoped write must carry the exact ETag returned by the last
read. The guard locks the project row ``FOR UPDATE`` and compares the header
to ``state_revision`` inside the same request transaction that will run the
mutation, so a stale write can never commit (acceptance §13: two requests
with the same ETag cannot both silently overwrite).

Missing header → 428 ``PRECONDITION_REQUIRED``; mismatch → 412
``STALE_PROJECT_STATE`` with the current revisions. Both reuse the existing
outer error envelope through ``AppError`` handling.
"""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.api.v1.common import project_etag
from app.core.exceptions import AppError
from app.db.document import lock_project
from app.db.models import Project

_REVISION_SUFFIX = re.compile(r'-s(\d+)"$')


class PreconditionRequiredError(AppError):
    """A protected write omitted the required If-Match header (§9.2)."""

    code = "PRECONDITION_REQUIRED"
    http_status = 428
    default_message = "If-Match header is required for this write"


class StaleProjectStateError(AppError):
    """If-Match does not equal the current state_revision (§9.2, A.2)."""

    code = "STALE_PROJECT_STATE"
    http_status = 412
    default_message = "The project changed after the client loaded it."


def _expected_revision(if_match: str) -> int:
    """Best-effort parse of the revision the client believed it held.

    A well-formed ETag ends in ``-s{revision}"``. An unparseable token still
    fails the exact comparison (412); ``0`` is used as the sentinel for
    "no readable revision" because revisions are positive integers.
    """
    match = _REVISION_SUFFIX.search(if_match)
    return int(match.group(1)) if match else 0


def require_if_match(
    request: Request,
    project_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Project:
    """Lock the project and verify If-Match before any mutation runs.

    Declared as a dependency so it shares the request-scoped session (and
    therefore the transaction) with the endpoint. The header is declared
    optional in OpenAPI on purpose: a required header would make FastAPI
    answer 422 when it is missing, while the contract demands 428.
    """
    if if_match is None:
        raise PreconditionRequiredError()
    project = lock_project(session, project_id)
    if if_match != project_etag(project_id, project.state_revision):
        raise StaleProjectStateError(
            details={
                "expected_state_revision": _expected_revision(if_match),
                "current_state_revision": project.state_revision,
                "current_simulation_revision": project.simulation_revision,
            }
        )
    return project
