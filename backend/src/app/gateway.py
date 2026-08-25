import logging
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx2
from pydantic import Field, ValidationError

from app.contracts import (
    ChatDeltaEvent,
    ChatDoneEvent,
    ChatErrorEvent,
    ChatRequest,
    ChatStartedEvent,
    ChatStreamEvent,
    ContractModel,
)

logger = logging.getLogger(__name__)


class _ExecutionResponse(ContractModel):
    request_id: UUID
    session_id: UUID
    status: str = Field(pattern="^completed$")
    output: str = Field(min_length=1, max_length=16_000)
    tools_used: tuple[str, ...] = ()


class UnavailableAgentGateway:
    """Safe placeholder used until the private agent-ai adapter exists."""

    async def stream(
        self,
        _request: ChatRequest,
        *,
        correlation_id: str,
    ) -> AsyncIterator[ChatStreamEvent]:
        response_id = uuid4()
        yield ChatStartedEvent(correlation_id=correlation_id, response_id=response_id)
        yield ChatErrorEvent(
            correlation_id=correlation_id,
            response_id=response_id,
            code="agent_unavailable",
            message="The assistant is temporarily unavailable.",
            retryable=True,
        )
        yield ChatDoneEvent(
            correlation_id=correlation_id,
            response_id=response_id,
            outcome="failed",
        )

    async def aclose(self) -> None:
        return None


class HttpAgentGateway:
    """HTTP adapter for the private, authenticated agent-ai execution API."""

    def __init__(
        self,
        *,
        base_url: str,
        connect_timeout_seconds: float,
        response_timeout_seconds: float,
        internal_token: str | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json"}
        if internal_token is not None:
            headers["Authorization"] = f"Bearer {internal_token}"
        self._client = httpx2.AsyncClient(
            base_url=base_url,
            headers=headers,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            timeout=httpx2.Timeout(
                connect=connect_timeout_seconds,
                read=response_timeout_seconds,
                write=connect_timeout_seconds,
                pool=connect_timeout_seconds,
            ),
            limits=httpx2.Limits(max_connections=50, max_keepalive_connections=20),
        )

    async def stream(
        self,
        request: ChatRequest,
        *,
        correlation_id: str,
    ) -> AsyncIterator[ChatStreamEvent]:
        response_id = request.client_message_id
        yield ChatStartedEvent(correlation_id=correlation_id, response_id=response_id)

        try:
            response = await self._client.post(
                "/internal/v1/executions",
                json={
                    "request_id": str(response_id),
                    "session_id": str(request.session_id),
                    "input": request.message,
                    "locale": request.locale,
                },
                headers={"X-Correlation-ID": correlation_id},
            )
        except httpx2.TimeoutException:
            logger.warning("agent request timed out correlation_id=%s", correlation_id)
            async for event in self._failure_events(
                correlation_id=correlation_id,
                response_id=response_id,
                code="agent_timeout",
                retryable=True,
            ):
                yield event
            return
        except httpx2.RequestError:
            logger.warning("agent request failed correlation_id=%s", correlation_id)
            async for event in self._failure_events(
                correlation_id=correlation_id,
                response_id=response_id,
                code="agent_unavailable",
                retryable=True,
            ):
                yield event
            return

        if response.status_code != 200:
            retryable = response.status_code == 429 or response.status_code >= 500
            logger.warning(
                "agent returned status=%s correlation_id=%s",
                response.status_code,
                correlation_id,
            )
            async for event in self._failure_events(
                correlation_id=correlation_id,
                response_id=response_id,
                code="agent_unavailable",
                retryable=retryable,
            ):
                yield event
            return

        try:
            execution = _ExecutionResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            logger.warning("agent returned an invalid contract correlation_id=%s", correlation_id)
            async for event in self._failure_events(
                correlation_id=correlation_id,
                response_id=response_id,
                code="agent_protocol_error",
                retryable=True,
            ):
                yield event
            return

        if execution.request_id != response_id or execution.session_id != request.session_id:
            logger.warning("agent response identity mismatch correlation_id=%s", correlation_id)
            async for event in self._failure_events(
                correlation_id=correlation_id,
                response_id=response_id,
                code="agent_protocol_error",
                retryable=True,
            ):
                yield event
            return

        for sequence, offset in enumerate(range(0, len(execution.output), 4_000)):
            yield ChatDeltaEvent(
                correlation_id=correlation_id,
                response_id=response_id,
                sequence=sequence,
                delta=execution.output[offset : offset + 4_000],
            )
        yield ChatDoneEvent(
            correlation_id=correlation_id,
            response_id=response_id,
            outcome="completed",
        )

    async def _failure_events(
        self,
        *,
        correlation_id: str,
        response_id: UUID,
        code: str,
        retryable: bool,
    ) -> AsyncIterator[ChatStreamEvent]:
        yield ChatErrorEvent(
            correlation_id=correlation_id,
            response_id=response_id,
            code=code,
            message="The assistant is temporarily unavailable.",
            retryable=retryable,
        )
        yield ChatDoneEvent(
            correlation_id=correlation_id,
            response_id=response_id,
            outcome="failed",
        )

    async def aclose(self) -> None:
        await self._client.aclose()
