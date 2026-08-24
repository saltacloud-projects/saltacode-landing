from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.contracts import HealthStatus
from app.dependencies import get_rate_limiter
from app.rate_limit import RateLimiter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthStatus)
async def live() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/ready",
    response_model=HealthStatus,
    responses={503: {"model": HealthStatus, "description": "Dependency not ready."}},
)
async def ready(
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> HealthStatus | JSONResponse:
    if not await rate_limiter.ready():
        return JSONResponse(status_code=503, content=HealthStatus(status="not_ready").model_dump())
    return HealthStatus(status="ready")
