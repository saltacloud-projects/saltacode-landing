"""Same-origin public endpoints for durable, resumable web chat."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.chat_v2.contracts import (
    BrowserCommercialContactRequest,
    BrowserMessageRequest,
    BrowserResetRequest,
    CommercialContactAccepted,
    ConversationEvent,
    EventsResponse,
    HistoryResponse,
    MessageAccepted,
    PrivateCommercialContactRequest,
    PrivateMessageRequest,
    PrivateResetRequest,
    ResetResponse,
    StreamDone,
    StreamFailure,
    TranscriptConsent,
)
from app.chat_v2.ports import (
    WebChatBlockedError,
    WebChatClientError,
    WebChatConflictError,
    WebChatSessionNotFoundError,
    WebChatUnprocessableError,
    WebChatV2Client,
)
from app.config import Settings
from app.contracts import ProblemDetails
from app.dependencies import (
    get_rate_limiter,
    get_session_manager,
    get_settings,
    get_web_chat_v2_client,
)
from app.errors import ApiError
from app.ports import RateLimitBackendError, RateLimitDecision, RateLimiter
from app.security import client_rate_limit_key, enforce_allowed_origin, rate_limit_client_identity
from app.session import SessionResolution, SignedSessionManager

router = APIRouter(prefix="/api/v2/chat", tags=["chat-v2"])
upgrade_router = APIRouter(prefix="/api/v1/chat", tags=["chat-v2-migration"])
_MAX_EVENT_CURSOR = 9_223_372_036_854_775_807


def _problem_response(description: str) -> dict[str, object]:
    return {
        "description": description,
        "content": {"application/problem+json": {"schema": ProblemDetails.model_json_schema()}},
    }


_MESSAGE_RESPONSES = {
    400: _problem_response("Privacy notice rejected."),
    403: _problem_response("Origin rejected."),
    409: _problem_response("Message idempotency conflict."),
    422: _problem_response("Request validation failed."),
    423: _problem_response("Conversation is not automated."),
    429: _problem_response("Rate limit exceeded."),
    503: _problem_response("Private chat service unavailable."),
}
_HISTORY_RESPONSES = {
    403: _problem_response("Origin rejected."),
    404: _problem_response("Chat session not found."),
    422: _problem_response("Request validation failed."),
    429: _problem_response("Rate limit exceeded."),
    503: _problem_response("Private chat service unavailable."),
}
_EVENT_RESPONSES = {
    200: {
        "description": "Resumable Server-Sent Events stream.",
        "content": {
            "text/event-stream": {
                "schema": {"type": "string"},
                "x-sse-event-schema": {
                    "oneOf": [
                        ConversationEvent.model_json_schema(),
                        StreamFailure.model_json_schema(),
                        StreamDone.model_json_schema(),
                    ]
                },
            }
        },
    },
    400: _problem_response("Event cursor rejected."),
    **_HISTORY_RESPONSES,
}
_RESET_RESPONSES = {
    400: _problem_response("Privacy notice rejected."),
    **_HISTORY_RESPONSES,
    423: _problem_response("Replacement session is not available."),
}
_COMMERCIAL_CONTACT_RESPONSES = {
    400: _problem_response("Privacy notice rejected."),
    403: _problem_response("Origin rejected."),
    404: _problem_response("Chat session not found."),
    409: _problem_response("Commercial contact idempotency conflict."),
    422: _problem_response("Commercial contact validation failed."),
    423: _problem_response("Conversation cannot accept commercial contact data."),
    429: _problem_response("Rate limit exceeded."),
    503: _problem_response("Private commercial service unavailable."),
}
_UPGRADE_RESPONSES = {
    403: _problem_response("Origin rejected."),
    404: _problem_response("Legacy chat session not found."),
    429: _problem_response("Rate limit exceeded."),
    503: _problem_response("Rate-limit service unavailable."),
}


@router.post(
    "/messages",
    response_model=MessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_MESSAGE_RESPONSES,
)
async def create_message(
    payload: BrowserMessageRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    sessions: Annotated[SignedSessionManager, Depends(get_session_manager)],
    client: Annotated[WebChatV2Client, Depends(get_web_chat_v2_client)],
) -> MessageAccepted:
    enforce_allowed_origin(request, settings)
    _require_current_privacy(payload.privacy_version, settings)
    decision = await _check_rate_limit(request, rate_limiter)
    session = sessions.resolve(request.cookies.get(settings.session_cookie_v2_name))
    try:
        accepted = await client.accept_message(
            PrivateMessageRequest(
                session_id=session.session_id,
                client_message_id=payload.client_message_id,
                route_key=settings.agent_route_key or "",
                content=payload.message,
                locale=payload.locale,
                consent=TranscriptConsent(
                    granted=True,
                    version=payload.privacy_version,
                ),
            ),
            correlation_id=request.state.correlation_id,
        )
    except WebChatClientError as error:
        _raise_public_error(error)
    _set_session_cookie(response, session, settings)
    _set_response_headers(response, rate_limit=decision)
    return accepted


@router.post(
    "/commercial-contact",
    response_model=CommercialContactAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_COMMERCIAL_CONTACT_RESPONSES,
)
async def create_commercial_contact(
    payload: BrowserCommercialContactRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    sessions: Annotated[SignedSessionManager, Depends(get_session_manager)],
    client: Annotated[WebChatV2Client, Depends(get_web_chat_v2_client)],
) -> CommercialContactAccepted:
    enforce_allowed_origin(request, settings)
    _require_current_privacy(payload.privacy_version, settings)
    decision = await _check_rate_limit(request, rate_limiter)
    session = _require_existing_session(request, settings, sessions)
    try:
        accepted = await client.accept_commercial_contact(
            PrivateCommercialContactRequest(
                session_id=session.session_id,
                route_key=settings.agent_route_key or "",
                client_request_id=payload.client_request_id,
                locale=payload.locale,
                policy_version=settings.chat_privacy_version,
                title=payload.title,
                summary=payload.summary,
                contact_kind=payload.contact_kind,
                contact_value=payload.contact_value,
                preferred_delivery_channel=payload.preferred_delivery_channel,
                quote_delivery_consent=payload.quote_delivery_consent,
                commercial_follow_up_consent=payload.commercial_follow_up_consent,
            ),
            correlation_id=request.state.correlation_id,
        )
    except WebChatClientError as error:
        _raise_commercial_contact_error(error)
    _set_response_headers(response, rate_limit=decision)
    return accepted


@router.get("/history", response_model=HistoryResponse, responses=_HISTORY_RESPONSES)
async def get_history(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    sessions: Annotated[SignedSessionManager, Depends(get_session_manager)],
    client: Annotated[WebChatV2Client, Depends(get_web_chat_v2_client)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> HistoryResponse:
    enforce_allowed_origin(request, settings)
    decision = await _check_rate_limit(request, rate_limiter)
    session = _require_existing_session(request, settings, sessions)
    try:
        history = await client.history(
            session_id=session.session_id,
            correlation_id=request.state.correlation_id,
            limit=limit,
        )
    except WebChatClientError as error:
        _raise_public_error(error)
    _set_response_headers(response, rate_limit=decision)
    return history


@router.get("/events", response_class=StreamingResponse, responses=_EVENT_RESPONSES)
async def stream_events(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    sessions: Annotated[SignedSessionManager, Depends(get_session_manager)],
    client: Annotated[WebChatV2Client, Depends(get_web_chat_v2_client)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    enforce_allowed_origin(request, settings)
    decision = await _check_rate_limit(request, rate_limiter)
    session = _require_existing_session(request, settings, sessions)
    after = _parse_last_event_id(last_event_id)
    try:
        first_page = await client.events(
            session_id=session.session_id,
            correlation_id=request.state.correlation_id,
            after=after,
            limit=settings.chat_v2_event_page_size,
        )
    except WebChatClientError as error:
        _raise_public_error(error)
    return StreamingResponse(
        _event_stream(
            request=request,
            client=client,
            session=session,
            correlation_id=request.state.correlation_id,
            first_page=first_page,
            settings=settings,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            ),
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
            "X-RateLimit-Remaining": str(decision.remaining),
        },
    )


@router.post("/session/reset", response_model=ResetResponse, responses=_RESET_RESPONSES)
async def reset_session(
    payload: BrowserResetRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    sessions: Annotated[SignedSessionManager, Depends(get_session_manager)],
    client: Annotated[WebChatV2Client, Depends(get_web_chat_v2_client)],
) -> ResetResponse:
    enforce_allowed_origin(request, settings)
    _require_current_privacy(payload.privacy_version, settings)
    decision = await _check_rate_limit(request, rate_limiter)
    current = _require_existing_session(request, settings, sessions)
    replacement = sessions.resolve(None)
    try:
        result = await client.reset_session(
            PrivateResetRequest(
                session_id=current.session_id,
                next_session_id=replacement.session_id,
                route_key=settings.agent_route_key or "",
                consent=TranscriptConsent(
                    granted=True,
                    version=payload.privacy_version,
                ),
            ),
            correlation_id=request.state.correlation_id,
        )
    except WebChatClientError as error:
        _raise_public_error(error)
    _set_session_cookie(response, replacement, settings)
    _set_response_headers(response, rate_limit=decision)
    return result


@upgrade_router.post(
    "/session/upgrade",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_UPGRADE_RESPONSES,
)
async def upgrade_legacy_session(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    sessions: Annotated[SignedSessionManager, Depends(get_session_manager)],
) -> None:
    enforce_allowed_origin(request, settings)
    decision = await _check_rate_limit(request, rate_limiter)
    legacy = sessions.resolve(request.cookies.get(settings.session_cookie_name))
    if legacy.is_new:
        raise _session_not_found()
    _set_session_cookie(response, legacy, settings)
    _set_response_headers(response, rate_limit=decision)


async def _event_stream(
    *,
    request: Request,
    client: WebChatV2Client,
    session: SessionResolution,
    correlation_id: str,
    first_page: EventsResponse,
    settings: Settings,
) -> AsyncIterator[str]:
    cursor = first_page.after
    page = first_page
    started_at = time.monotonic()
    heartbeat_at = started_at
    try:
        while time.monotonic() - started_at < settings.chat_v2_stream_max_seconds:
            if await request.is_disconnected():
                return
            for event in page.events:
                cursor = event.cursor
                yield (
                    f"id: {event.cursor}\n"
                    f"event: {event.event_type}\n"
                    f"data: {event.model_dump_json()}\n\n"
                )
            if page.has_more:
                page = await client.events(
                    session_id=session.session_id,
                    correlation_id=correlation_id,
                    after=cursor,
                    limit=settings.chat_v2_event_page_size,
                )
                continue
            now = time.monotonic()
            if now - heartbeat_at >= settings.chat_v2_heartbeat_seconds:
                yield ": heartbeat\n\n"
                heartbeat_at = now
            await asyncio.sleep(settings.chat_v2_poll_seconds)
            page = await client.events(
                session_id=session.session_id,
                correlation_id=correlation_id,
                after=cursor,
                limit=settings.chat_v2_event_page_size,
            )
    except WebChatClientError:
        yield f"event: chat.error\ndata: {StreamFailure().model_dump_json()}\n\n"
        yield f"event: chat.done\ndata: {StreamDone().model_dump_json()}\n\n"


async def _check_rate_limit(
    request: Request,
    rate_limiter: RateLimiter,
) -> RateLimitDecision:
    identity = rate_limit_client_identity(request)
    try:
        decision = await rate_limiter.check(client_rate_limit_key(identity))
    except RateLimitBackendError:
        raise ApiError(
            status_code=503,
            code="rate_limit_unavailable",
            title="Service temporarily unavailable",
            detail="The request cannot be accepted right now.",
        ) from None
    if not decision.allowed:
        raise ApiError(
            status_code=429,
            code="rate_limit_exceeded",
            title="Rate limit exceeded",
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    return decision


def _require_current_privacy(version: str, settings: Settings) -> None:
    if version != settings.chat_privacy_version:
        raise ApiError(
            status_code=400,
            code="privacy_version_unsupported",
            title="Privacy version unsupported",
            detail="Please review and accept the current privacy notice before continuing.",
        )


def _require_existing_session(
    request: Request,
    settings: Settings,
    sessions: SignedSessionManager,
) -> SessionResolution:
    session = sessions.resolve(request.cookies.get(settings.session_cookie_v2_name))
    if session.is_new:
        raise _session_not_found()
    return session


def _parse_last_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        cursor = int(value)
    except ValueError as error:
        raise _invalid_request() from error
    if cursor < 0 or cursor > _MAX_EVENT_CURSOR or str(cursor) != value:
        raise _invalid_request()
    return cursor


def _set_session_cookie(
    response: Response,
    session: SessionResolution,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=settings.session_cookie_v2_name,
        value=session.cookie_value,
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/api/v2/chat",
    )


def _set_response_headers(
    response: Response,
    *,
    rate_limit: RateLimitDecision,
) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-RateLimit-Remaining"] = str(rate_limit.remaining)


def _raise_public_error(error: WebChatClientError) -> None:
    if isinstance(error, WebChatSessionNotFoundError):
        raise _session_not_found() from error
    if isinstance(error, WebChatConflictError):
        raise ApiError(
            status_code=409,
            code="message_conflict",
            title="Message conflict",
            detail="This message identifier is already in use.",
        ) from error
    if isinstance(error, WebChatBlockedError):
        raise ApiError(
            status_code=423,
            code="chat_not_automated",
            title="Chat temporarily paused",
            detail="The conversation is not accepting automated messages.",
        ) from error
    raise ApiError(
        status_code=503,
        code="agent_unavailable",
        title="Assistant temporarily unavailable",
        detail="The assistant cannot complete the request right now.",
    ) from error


def _raise_commercial_contact_error(error: WebChatClientError) -> None:
    if isinstance(error, WebChatSessionNotFoundError):
        raise _session_not_found() from error
    if isinstance(error, WebChatConflictError):
        raise ApiError(
            status_code=409,
            code="commercial_contact_conflict",
            title="Commercial contact conflict",
            detail="This commercial request identifier is already in use.",
        ) from error
    if isinstance(error, WebChatUnprocessableError):
        raise ApiError(
            status_code=422,
            code="commercial_contact_rejected",
            title="Commercial contact rejected",
            detail="The contact or consent evidence could not be accepted.",
        ) from error
    if isinstance(error, WebChatBlockedError):
        raise ApiError(
            status_code=423,
            code="commercial_contact_blocked",
            title="Commercial contact blocked",
            detail="The conversation cannot accept commercial contact data.",
        ) from error
    raise ApiError(
        status_code=503,
        code="commercial_service_unavailable",
        title="Commercial service temporarily unavailable",
        detail="The commercial request cannot be accepted right now.",
    ) from error


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code="chat_session_not_found",
        title="Chat session not found",
        detail="The chat session could not be found.",
    )


def _invalid_request() -> ApiError:
    return ApiError(
        status_code=400,
        code="invalid_chat_cursor",
        title="Invalid chat request",
        detail="The chat event cursor is invalid.",
    )
