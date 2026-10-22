import logging

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

logger = logging.getLogger("network_simulator")

app = FastAPI(
    title=settings.app_name,
    description="Backend API for an AI-powered 3D network learning and troubleshooting simulator.",
    version=settings.app_version,
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    logger.info("Health check requested")
    return {"status": "ok"}
