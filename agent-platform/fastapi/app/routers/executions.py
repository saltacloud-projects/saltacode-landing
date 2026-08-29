"""Private execution API for authenticated BFF and channel adapters."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_internal_bearer
from app.dependencies import get_db, get_redis
from app.schemas.executions import InternalExecutionRequest, InternalExecutionResponse
from app.services.chat_application import (
    AgentNotReady,
    ExecutionInProgress,
    TranscriptConsentRequired,
    chat_application_service,
)

router = APIRouter(
    prefix="/internal/v1/executions",
    tags=["executions"],
    dependencies=[Depends(require_internal_bearer)],
)


@router.post("", response_model=InternalExecutionResponse)
async def execute(
    request: InternalExecutionRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    try:
        outcome = await chat_application_service.execute_web(db, request, redis=redis)
    except TranscriptConsentRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ExecutionInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except AgentNotReady as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return InternalExecutionResponse(
        request_id=request.request_id,
        session_id=request.session_id,
        output=outcome.output,
        tools_used=outcome.tools_used,
    )
