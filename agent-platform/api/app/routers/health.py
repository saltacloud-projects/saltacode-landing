"""Liveness and dependency-readiness endpoints."""

import logging

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.database import engine

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health():
    """
    Liveness probe — responde si el proceso FastAPI está corriendo.
    Usado por el HEALTHCHECK de Docker y el healthcheck de Compose.
    """
    return {"status": "ok", "service": "agent-platform-api"}


@router.get("/ready")
async def ready(request: Request, response: Response):
    """
    Readiness probe — verifica conectividad con PostgreSQL y Redis.
    Usa el cliente Redis compartido (app.state.redis) sin abrir nueva conexión.
    """
    checks: dict[str, str] = {}

    # Verificar PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("database_health_check_failed", extra={"error": str(exc)})
        checks["database"] = "error"

    # Verificar Redis — cliente compartido desde app.state
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("redis_health_check_failed", extra={"error": str(exc)})
        checks["redis"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
