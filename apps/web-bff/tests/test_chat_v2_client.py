from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx2
import pytest

from app.chat_v2.client import HttpWebChatV2Client
from app.chat_v2.contracts import (
    PrivateCommercialContactRequest,
    PrivateMessageRequest,
    TranscriptConsent,
)
from app.chat_v2.ports import (
    WebChatBlockedError,
    WebChatConflictError,
    WebChatProtocolError,
    WebChatSessionNotFoundError,
    WebChatUnavailableError,
    WebChatUnprocessableError,
)


def make_client(handler) -> HttpWebChatV2Client:
    return HttpWebChatV2Client(
        base_url="http://agent-platform:8001",
        route_key="saltacode-landing",
        connect_timeout_seconds=1,
        response_timeout_seconds=2,
        internal_token="x" * 32,
        transport=httpx2.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_private_message_adapter_owns_auth_route_and_correlation() -> None:
    session_id = uuid4()
    client_message_id = uuid4()

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/internal/v2/web/messages"
        assert request.headers["authorization"] == f"Bearer {'x' * 32}"
        assert request.headers["x-correlation-id"] == "correlation-private-v2"
        payload = json.loads(request.content)
        assert payload["route_key"] == "saltacode-landing"
        assert payload["session_id"] == str(session_id)
        return httpx2.Response(
            202,
            json={
                "client_message_id": str(client_message_id),
                "message_id": str(uuid4()),
                "status": "accepted",
                "event_cursor": 1,
                "duplicate": False,
            },
        )

    client = make_client(handler)
    try:
        response = await client.accept_message(
            PrivateMessageRequest(
                session_id=session_id,
                client_message_id=client_message_id,
                route_key="saltacode-landing",
                content="Necesito una web.",
                locale="es-AR",
                consent=TranscriptConsent(granted=True, version="privacy-v2"),
            ),
            correlation_id="correlation-private-v2",
        )
    finally:
        await client.aclose()

    assert response.client_message_id == client_message_id


@pytest.mark.asyncio
async def test_private_message_adapter_rejects_changed_identity() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            202,
            json={
                "client_message_id": str(uuid4()),
                "message_id": str(uuid4()),
                "status": "accepted",
                "event_cursor": 1,
                "duplicate": False,
            },
        )

    request = PrivateMessageRequest(
        session_id=uuid4(),
        client_message_id=uuid4(),
        route_key="saltacode-landing",
        content="Necesito una web.",
        locale="es-AR",
        consent=TranscriptConsent(granted=True, version="privacy-v2"),
    )
    client = make_client(handler)
    try:
        with pytest.raises(WebChatProtocolError, match="identity changed"):
            await client.accept_message(request, correlation_id="correlation-private-v2")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_private_commercial_contact_adapter_owns_auth_route_and_correlation() -> None:
    session_id = uuid4()
    opportunity_id = uuid4()
    target_agent_id = uuid4()

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/internal/v2/web/commercial-contact"
        assert request.headers["authorization"] == f"Bearer {'x' * 32}"
        assert request.headers["x-correlation-id"] == "commercial-correlation"
        payload = json.loads(request.content)
        assert payload == {
            "session_id": str(session_id),
            "route_key": "saltacode-landing",
            "client_request_id": payload["client_request_id"],
            "locale": "es-AR",
            "title": "Sitio web industrial",
            "summary": "Catálogo y contacto comercial.",
            "contact_kind": "email",
            "contact_value": "lead@example.com",
            "preferred_delivery_channel": "email",
            "quote_delivery_consent": True,
            "commercial_follow_up_consent": False,
            "policy_version": "privacy-v2",
        }
        return httpx2.Response(
            202,
            json={
                "opportunity_id": str(opportunity_id),
                "target_agent_id": str(target_agent_id),
                "status": "accepted",
            },
        )

    client_request_id = uuid4()
    client = make_client(handler)
    try:
        response = await client.accept_commercial_contact(
            PrivateCommercialContactRequest(
                session_id=session_id,
                route_key="saltacode-landing",
                client_request_id=client_request_id,
                locale="es-AR",
                title="Sitio web industrial",
                summary="Catálogo y contacto comercial.",
                contact_kind="email",
                contact_value="lead@example.com",
                preferred_delivery_channel="email",
                quote_delivery_consent=True,
                commercial_follow_up_consent=False,
                policy_version="privacy-v2",
            ),
            correlation_id="commercial-correlation",
        )
    finally:
        await client.aclose()

    assert response.opportunity_id == opportunity_id
    assert response.target_agent_id == target_agent_id


@pytest.mark.asyncio
async def test_private_commercial_contact_adapter_maps_invalid_evidence() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(422, text="private contact detail")

    client = make_client(handler)
    try:
        with pytest.raises(WebChatUnprocessableError) as caught:
            await client.accept_commercial_contact(
                PrivateCommercialContactRequest(
                    session_id=uuid4(),
                    route_key="saltacode-landing",
                    client_request_id=uuid4(),
                    locale="es-AR",
                    title="Sitio web industrial",
                    contact_kind="email",
                    contact_value="lead@example.com",
                    preferred_delivery_channel="email",
                    quote_delivery_consent=True,
                    commercial_follow_up_consent=False,
                    policy_version="privacy-v2",
                ),
                correlation_id="commercial-correlation",
            )
    finally:
        await client.aclose()

    assert "private contact detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_private_commercial_contact_transport_failure_does_not_log_contact_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    contact_value = "private-lead@example.com"

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"failed for {contact_value}", request=request)

    client = make_client(handler)
    try:
        with pytest.raises(WebChatUnavailableError):
            await client.accept_commercial_contact(
                PrivateCommercialContactRequest(
                    session_id=uuid4(),
                    route_key="saltacode-landing",
                    client_request_id=uuid4(),
                    locale="es-AR",
                    title="Sitio web industrial",
                    contact_kind="email",
                    contact_value=contact_value,
                    preferred_delivery_channel="email",
                    quote_delivery_consent=True,
                    commercial_follow_up_consent=False,
                    policy_version="privacy-v2",
                ),
                correlation_id="commercial-correlation",
            )
    finally:
        await client.aclose()

    assert contact_value not in caplog.text
    assert "commercial-correlation" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (404, WebChatSessionNotFoundError),
        (409, WebChatConflictError),
        (423, WebChatBlockedError),
        (401, WebChatUnavailableError),
        (500, WebChatUnavailableError),
    ],
)
async def test_private_adapter_maps_status_without_leaking_body(
    status_code: int,
    error_type: type[Exception],
) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, text="private-secret-detail")

    client = make_client(handler)
    try:
        with pytest.raises(error_type) as caught:
            await client.history(
                session_id=uuid4(),
                correlation_id="correlation-private-v2",
                limit=100,
            )
    finally:
        await client.aclose()

    assert "private-secret-detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_private_adapter_rejects_non_monotonic_event_page() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        now = datetime.now(UTC).isoformat()
        return httpx2.Response(
            200,
            json={
                "after": 3,
                "next_cursor": 4,
                "has_more": False,
                "events": [
                    {
                        "schema_version": "2",
                        "cursor": 5,
                        "event_type": "chat.message",
                        "occurred_at": now,
                        "payload": {"content": "first"},
                    },
                    {
                        "schema_version": "2",
                        "cursor": 4,
                        "event_type": "chat.message",
                        "occurred_at": now,
                        "payload": {"content": "second"},
                    },
                ],
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(WebChatProtocolError, match="not monotonic"):
            await client.events(
                session_id=uuid4(),
                correlation_id="correlation-private-v2",
                after=3,
                limit=100,
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_private_adapter_rejects_non_advancing_paginated_event_page() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "after": 3,
                "next_cursor": 3,
                "has_more": True,
                "events": [],
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(WebChatProtocolError, match="cannot advance"):
            await client.events(
                session_id=uuid4(),
                correlation_id="correlation-private-v2",
                after=3,
                limit=100,
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_private_adapter_rejects_private_fields_in_event_payload() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "after": 0,
                "next_cursor": 1,
                "has_more": False,
                "events": [
                    {
                        "schema_version": "2",
                        "cursor": 1,
                        "event_type": "chat.message",
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "payload": {"metadata": {"conversation_id": str(uuid4())}},
                    }
                ],
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(WebChatProtocolError, match="contract is invalid"):
            await client.events(
                session_id=uuid4(),
                correlation_id="correlation-private-v2",
                after=0,
                limit=100,
            )
    finally:
        await client.aclose()
