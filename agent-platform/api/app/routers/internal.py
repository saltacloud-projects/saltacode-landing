"""Authenticated internal diagnostics."""

from fastapi import APIRouter, Depends

from app.config import settings
from app.core.security import require_api_key

router = APIRouter(tags=["internal"])


@router.get("/ping", dependencies=[Depends(require_api_key)])
async def ping():
    """Verificación de conectividad."""
    return {"status": "pong", "service": "agent-platform-api"}


@router.get("/status", dependencies=[Depends(require_api_key)])
async def service_status():
    """Estado resumido del servicio para monitoreo."""
    return {
        "service": "agent-platform-api",
        "status": "operational",
        "version": settings.app_version,
        "env": settings.fastapi_env,
    }
