"""Aggregate ``/api/v1`` router (TASK-07 §14.2 step 4).

Mounted once in ``app/main.py`` with ``prefix="/api/v1"`` (§11.1). Query
projections (step 6), the Ping adapter (step 7) and the revision guard
(step 5) extend this surface in their own steps.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import connections, devices, interfaces, projects, queries, static_routes

api_v1_router = APIRouter()
api_v1_router.include_router(projects.router)
api_v1_router.include_router(devices.router)
api_v1_router.include_router(interfaces.router)
api_v1_router.include_router(connections.router)
api_v1_router.include_router(static_routes.router)
api_v1_router.include_router(queries.router)
