import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.db.session import create_db_engine, create_session_factory

settings = get_settings()
configure_logging(settings.log_level)

logger = logging.getLogger("network_simulator")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the engine/session factory once; dispose the pool on shutdown."""
    engine = create_db_engine()
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)
    logger.info("Database engine and session factory initialised")
    try:
        yield
    finally:
        engine.dispose()
        logger.info("Database engine disposed")


app = FastAPI(
    title=settings.app_name,
    description="Backend API for an AI-powered 3D network learning and troubleshooting simulator.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    logger.info("Health check requested")
    return {"status": "ok"}
