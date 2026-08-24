from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter

from app.config import Settings
from app.contracts import ChatRequest, ChatStreamEvent, ProblemDetails
from app.dependencies import get_agent_gateway, get_rate_limiter, get_settings
from app.errors import ApiError
from app.gateway import AgentGateway
from app.rate_limit import RateLimitBackendError, RateLimiter
from app.security import client_rate_limit_key, enforce_allowed_origin, rate_limit_client_identity

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_STREAM_EVENT_SCHEMA = TypeAdapter(ChatStreamEvent).json_schema()


def _problem_response(description: str) -> dict[str, object]:
    return {
        "description": description,
        "content": {"application/problem+json": {"schema": ProblemDetails.model_json_schema()}},
    }


_CHAT_RESPONSES = {
    200: {
        "description": "Versioned Server-Sent Events stream.",
        "content": {
            "text/event-stream": {
                "schema": {"type": "string"},
                "x-sse-event-schema": _STREAM_EVENT_SCHEMA,
            }
        },
    },
    400: _problem_response("Client address rejected."),
    403: _problem_response("Origin rejected."),
    422: _problem_response("Request validation failed."),
    429: _problem_response("Rate limit exceeded."),
    503: _problem_response("Rate-limit service unavailable."),
}


def _encode_sse(event: ChatStreamEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


async def _encoded_stream(events: AsyncIterator[ChatStreamEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield _encode_sse(event)


@router.post("", response_class=StreamingResponse, responses=_CHAT_RESPONSES)
async def create_chat_message(
    payload: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    gateway: Annotated[AgentGateway, Depends(get_agent_gateway)],
) -> StreamingResponse:
    enforce_allowed_origin(request, settings)

    client_identity = rate_limit_client_identity(request)
    try:
        decision = await rate_limiter.check(client_rate_limit_key(client_identity))
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

    correlation_id = request.state.correlation_id
    events = gateway.stream(payload, correlation_id=correlation_id)
    return StreamingResponse(
        _encoded_stream(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-RateLimit-Remaining": str(decision.remaining),
        },
    )
