"""Private durable web-chat API consumed by the same-origin BFF."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_internal_bearer
from app.dependencies import get_db
from app.schemas.web_chat_v2 import (
    ROUTE_KEY_PATTERN,
    WebEventsResponse,
    WebHistoryResponse,
    WebMessageAccepted,
    WebMessageRequest,
    WebSessionResetRequest,
    WebSessionResetResponse,
)
from app.services.web_chat_v2 import (
    WebChatConsentRequiredError,
    WebChatRequestConflictError,
    WebChatRouteUnavailableError,
    WebChatSessionBlockedError,
    WebChatSessionNotFoundError,
    WebChatV2Error,
    web_chat_v2_service,
)

router = APIRouter(
    prefix="/internal/v2/web",
    tags=["web-chat-v2"],
    dependencies=[Depends(require_internal_bearer)],
)


@router.post(
    "/messages",
    response_model=WebMessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def accept_message(
    request: WebMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> WebMessageAccepted:
    try:
        response = await web_chat_v2_service.accept_message(db, request)
        await db.commit()
        return response
    except WebChatConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Transcript consent is required.",
        ) from exc
    except WebChatRequestConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client message id conflicts with stored input.",
        ) from exc
    except WebChatSessionBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Web chat session is not available for automation.",
        ) from exc
    except WebChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Web chat session was not found.",
        ) from exc
    except WebChatRouteUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web chat route is unavailable.",
        ) from exc
    except WebChatV2Error as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid durable web-chat request.",
        ) from exc


@router.get("/history", response_model=WebHistoryResponse)
async def history(
    session_id: UUID,
    route_key: str = Query(min_length=1, max_length=120, pattern=ROUTE_KEY_PATTERN),
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> WebHistoryResponse:
    try:
        return await web_chat_v2_service.history(
            db,
            session_id=session_id,
            route_key=route_key,
            limit=limit,
        )
    except WebChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Web chat session was not found.",
        ) from exc
    except WebChatRouteUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web chat route is unavailable.",
        ) from exc


@router.get("/events", response_model=WebEventsResponse)
async def events(
    session_id: UUID,
    route_key: str = Query(min_length=1, max_length=120, pattern=ROUTE_KEY_PATTERN),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> WebEventsResponse:
    try:
        return await web_chat_v2_service.events_after(
            db,
            session_id=session_id,
            route_key=route_key,
            after=after,
            limit=limit,
        )
    except WebChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Web chat session was not found.",
        ) from exc
    except WebChatRouteUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web chat route is unavailable.",
        ) from exc


@router.post("/session/reset", response_model=WebSessionResetResponse)
async def reset_session(
    request: WebSessionResetRequest,
    db: AsyncSession = Depends(get_db),
) -> WebSessionResetResponse:
    try:
        response = await web_chat_v2_service.reset_session(db, request)
        await db.commit()
        return response
    except WebChatConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Transcript consent is required.",
        ) from exc
    except WebChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Web chat session was not found.",
        ) from exc
    except WebChatSessionBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Replacement web chat session is not available.",
        ) from exc
    except WebChatRouteUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web chat route is unavailable.",
        ) from exc
