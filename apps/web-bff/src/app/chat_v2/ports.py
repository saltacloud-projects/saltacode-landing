"""Consumer-owned port for the private durable web-chat API."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.chat_v2.contracts import (
    EventsResponse,
    HistoryResponse,
    MessageAccepted,
    PrivateCommercialContactAccepted,
    PrivateCommercialContactRequest,
    PrivateMessageRequest,
    PrivateResetRequest,
    ResetResponse,
)


class WebChatClientError(Exception):
    """Base safe failure for the private web-chat dependency."""


class WebChatUnavailableError(WebChatClientError):
    """The private dependency cannot safely satisfy the request."""


class WebChatSessionNotFoundError(WebChatClientError):
    """The signed browser session has no conversation in this route."""


class WebChatConflictError(WebChatClientError):
    """The caller reused an idempotency identity with different content."""


class WebChatBlockedError(WebChatClientError):
    """The conversation cannot accept the requested automated action."""


class WebChatUnprocessableError(WebChatClientError):
    """The private service rejected invalid commercial evidence or consent."""


class WebChatProtocolError(WebChatUnavailableError):
    """The private service returned an invalid or inconsistent contract."""


class WebChatV2Client(Protocol):
    async def accept_message(
        self,
        request: PrivateMessageRequest,
        *,
        correlation_id: str,
    ) -> MessageAccepted: ...

    async def accept_commercial_contact(
        self,
        request: PrivateCommercialContactRequest,
        *,
        correlation_id: str,
    ) -> PrivateCommercialContactAccepted: ...

    async def history(
        self,
        *,
        session_id: UUID,
        correlation_id: str,
        limit: int,
    ) -> HistoryResponse: ...

    async def events(
        self,
        *,
        session_id: UUID,
        correlation_id: str,
        after: int,
        limit: int,
    ) -> EventsResponse: ...

    async def reset_session(
        self,
        request: PrivateResetRequest,
        *,
        correlation_id: str,
    ) -> ResetResponse: ...

    async def aclose(self) -> None: ...
