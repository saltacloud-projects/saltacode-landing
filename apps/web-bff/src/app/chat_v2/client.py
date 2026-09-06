"""HTTP adapter for the private Agent Platform web-chat v2 API."""

from __future__ import annotations

import logging
from itertools import pairwise
from typing import TypeVar
from uuid import UUID

import httpx2
from pydantic import ValidationError

from app.chat_v2.contracts import (
    EventsResponse,
    HistoryResponse,
    MessageAccepted,
    PrivateMessageRequest,
    PrivateResetRequest,
    ResetResponse,
    StrictContract,
)
from app.chat_v2.ports import (
    WebChatBlockedError,
    WebChatConflictError,
    WebChatProtocolError,
    WebChatSessionNotFoundError,
    WebChatUnavailableError,
)

logger = logging.getLogger(__name__)
ResponseContract = TypeVar("ResponseContract", bound=StrictContract)


class UnavailableWebChatV2Client:
    """Fail-closed client used when Agent Platform is not configured."""

    async def accept_message(self, *_args, **_kwargs) -> MessageAccepted:
        raise WebChatUnavailableError("web chat is not configured")

    async def history(self, **_kwargs) -> HistoryResponse:
        raise WebChatUnavailableError("web chat is not configured")

    async def events(self, **_kwargs) -> EventsResponse:
        raise WebChatUnavailableError("web chat is not configured")

    async def reset_session(self, *_args, **_kwargs) -> ResetResponse:
        raise WebChatUnavailableError("web chat is not configured")

    async def aclose(self) -> None:
        return None


class HttpWebChatV2Client:
    """Authenticated adapter that never exposes private response details."""

    def __init__(
        self,
        *,
        base_url: str,
        route_key: str,
        connect_timeout_seconds: float,
        response_timeout_seconds: float,
        internal_token: str | None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._route_key = route_key
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

    async def accept_message(
        self,
        request: PrivateMessageRequest,
        *,
        correlation_id: str,
    ) -> MessageAccepted:
        self._require_route(request.route_key)
        response = await self._request(
            "POST",
            "/internal/v2/web/messages",
            response_type=MessageAccepted,
            expected_status=202,
            correlation_id=correlation_id,
            json=request.model_dump(mode="json"),
        )
        if response.client_message_id != request.client_message_id:
            raise WebChatProtocolError("private message identity changed")
        return response

    async def history(
        self,
        *,
        session_id: UUID,
        correlation_id: str,
        limit: int,
    ) -> HistoryResponse:
        response = await self._request(
            "GET",
            "/internal/v2/web/history",
            response_type=HistoryResponse,
            expected_status=200,
            correlation_id=correlation_id,
            params={
                "session_id": str(session_id),
                "route_key": self._route_key,
                "limit": limit,
            },
        )
        if len(response.messages) > limit:
            raise WebChatProtocolError("private history exceeded requested limit")
        return response

    async def events(
        self,
        *,
        session_id: UUID,
        correlation_id: str,
        after: int,
        limit: int,
    ) -> EventsResponse:
        response = await self._request(
            "GET",
            "/internal/v2/web/events",
            response_type=EventsResponse,
            expected_status=200,
            correlation_id=correlation_id,
            params={
                "session_id": str(session_id),
                "route_key": self._route_key,
                "after": after,
                "limit": limit,
            },
        )
        self._validate_event_page(
            response,
            requested_after=after,
            requested_limit=limit,
        )
        return response

    async def reset_session(
        self,
        request: PrivateResetRequest,
        *,
        correlation_id: str,
    ) -> ResetResponse:
        self._require_route(request.route_key)
        return await self._request(
            "POST",
            "/internal/v2/web/session/reset",
            response_type=ResetResponse,
            expected_status=200,
            correlation_id=correlation_id,
            json=request.model_dump(mode="json"),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        response_type: type[ResponseContract],
        expected_status: int,
        correlation_id: str,
        **kwargs,
    ) -> ResponseContract:
        try:
            response = await self._client.request(
                method,
                path,
                headers={"X-Correlation-ID": correlation_id},
                **kwargs,
            )
        except httpx2.TimeoutException as error:
            logger.warning("web chat private request timed out correlation_id=%s", correlation_id)
            raise WebChatUnavailableError("private web chat timed out") from error
        except httpx2.RequestError as error:
            logger.warning("web chat private request failed correlation_id=%s", correlation_id)
            raise WebChatUnavailableError("private web chat is unavailable") from error

        if response.status_code != expected_status:
            self._raise_status(response.status_code)
        try:
            return response_type.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            logger.warning(
                "web chat private contract invalid correlation_id=%s",
                correlation_id,
            )
            raise WebChatProtocolError("private web chat contract is invalid") from error

    @staticmethod
    def _raise_status(status_code: int) -> None:
        if status_code == 404:
            raise WebChatSessionNotFoundError("web chat session was not found")
        if status_code == 409:
            raise WebChatConflictError("web chat request conflicts with persisted input")
        if status_code == 423:
            raise WebChatBlockedError("web chat session is not automated")
        raise WebChatUnavailableError("private web chat rejected the request")

    @staticmethod
    def _validate_event_page(
        response: EventsResponse,
        *,
        requested_after: int,
        requested_limit: int,
    ) -> None:
        cursors = [event.cursor for event in response.events]
        if response.after != requested_after:
            raise WebChatProtocolError("private event cursor identity changed")
        if len(cursors) > requested_limit:
            raise WebChatProtocolError("private event page exceeded requested limit")
        if response.has_more and not cursors:
            raise WebChatProtocolError("private event page cannot advance")
        if any(cursor <= requested_after for cursor in cursors):
            raise WebChatProtocolError("private event cursor did not advance")
        if any(current >= following for current, following in pairwise(cursors)):
            raise WebChatProtocolError("private event cursors are not monotonic")
        expected_next = cursors[-1] if cursors else requested_after
        if response.next_cursor != expected_next:
            raise WebChatProtocolError("private event next cursor is inconsistent")

    def _require_route(self, route_key: str) -> None:
        if route_key != self._route_key:
            raise WebChatProtocolError("private web chat route identity changed")

    async def aclose(self) -> None:
        await self._client.aclose()
