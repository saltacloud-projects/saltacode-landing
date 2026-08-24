"""Private, versioned HTTP contracts."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from saltacode_agent.application.errors import RuntimeUnavailableError
from saltacode_agent.domain.contracts import (
    ErrorResponse,
    ExecutionRequest,
    ExecutionResponse,
    LivenessResponse,
    ReadinessResponse,
)
from saltacode_agent.transport.http.dependencies import (
    ServicesDependency,
    require_internal_access,
)

router = APIRouter()


@router.get("/health/live", response_model=LivenessResponse, tags=["health"])
async def liveness(services: ServicesDependency) -> LivenessResponse:
    return LivenessResponse(service=services.settings.service_name)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    tags=["health"],
)
async def readiness(services: ServicesDependency) -> ReadinessResponse | JSONResponse:
    checks = tuple(await services.readiness.check())
    payload = ReadinessResponse(
        status="ready" if checks and all(check.ready for check in checks) else "not_ready",
        checks=checks,
    )
    if payload.status == "not_ready":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )
    return payload


@router.post(
    "/internal/v1/executions",
    response_model=ExecutionResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
    dependencies=[Depends(require_internal_access)],
    tags=["internal"],
)
async def execute(
    request: ExecutionRequest,
    services: ServicesDependency,
) -> ExecutionResponse | JSONResponse:
    try:
        return await services.runtime.execute(request)
    except RuntimeUnavailableError:
        error = ErrorResponse(
            request_id=request.request_id,
            code="agent_runtime_unavailable",
            message="Agent execution is temporarily unavailable.",
            retryable=True,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error.model_dump(mode="json"),
        )
