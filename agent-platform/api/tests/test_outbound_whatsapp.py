"""Focused contracts for the WhatsApp outbound adapter."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundMessage
from app.ports.outbound import Accepted, Rejected, Unknown
from app.services.outbound_whatsapp import WhatsAppOutboundAdapter


class _FakeClient:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _context(*, kind="text", payload=None):
    agent_id = uuid4()
    connection = ChannelConnection(
        id=uuid4(),
        name="Test connection",
        slug=f"test-{uuid4().hex}",
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        version=0,
        external_account_id="123456789",
        is_active=True,
        settings_json={},
    )
    route = ChannelAgentRoute(
        id=uuid4(),
        channel="whatsapp",
        version=0,
        route_key="test-route",
        channel_connection_id=connection.id,
        agent_id=agent_id,
        is_active=True,
    )
    message = OutboundMessage(
        id=uuid4(),
        conversation_id=uuid4(),
        agent_id=agent_id,
        channel_route_id=route.id,
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        channel_connection_id=connection.id,
        route_version=0,
        connection_version=0,
        chat_message_id=None,
        kind=kind,
        payload_json=payload or {"text": "Hello"},
        destination="5493870000000",
        sender_type="automation",
        control_version=0,
        sequence=1,
        idempotency_key="test-key",
        payload_hash="a" * 64,
        correlation_id="test-correlation",
        status="dispatching",
        last_attempt_number=1,
    )
    return message, route, connection


def _response(status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://graph.facebook.com/test")
    return httpx.Response(status_code, json=payload, request=request)


@pytest.mark.asyncio
async def test_text_delivery_maps_provider_acceptance_without_exposing_credentials(
    monkeypatch,
):
    from app.services import outbound_whatsapp as module

    message, route, connection = _context()
    client = _FakeClient([_response(200, {"messages": [{"id": "wamid.test"}]})])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        module.whatsapp_service,
        "resolve_connection",
        lambda *_args, **_kwargs: SimpleNamespace(
            access_token="must-not-leak",
            phone_number_id="123456789",
        ),
    )

    result = await WhatsAppOutboundAdapter().deliver(
        message=message,
        route=route,
        connection=connection,
    )

    assert result == Accepted("wamid.test")
    assert client.requests[0][1]["json"]["to"] == "543870000000"
    assert client.requests[0][1]["json"]["text"]["body"] == "Hello"
    assert "must-not-leak" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_response", "expected"),
    [
        (
            _response(400, {"error": {"message": "private"}}),
            Rejected("provider_http_400"),
        ),
        (
            _response(503, {"error": {"message": "private"}}),
            Unknown("provider_http_503"),
        ),
        (
            httpx.ReadTimeout(
                "timed out",
                request=httpx.Request("POST", "https://graph.facebook.com/test"),
            ),
            Unknown("provider_timeout"),
        ),
    ],
)
async def test_provider_failures_are_classified_without_response_bodies(
    monkeypatch,
    provider_response,
    expected,
):
    from app.services import outbound_whatsapp as module

    message, route, connection = _context()
    client = _FakeClient([provider_response])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        module.whatsapp_service,
        "resolve_connection",
        lambda *_args, **_kwargs: SimpleNamespace(
            access_token="must-not-leak",
            phone_number_id="123456789",
        ),
    )

    result = await WhatsAppOutboundAdapter().deliver(
        message=message,
        route=route,
        connection=connection,
    )

    assert result == expected
    assert "private" not in repr(result)
    assert "must-not-leak" not in repr(result)


@pytest.mark.asyncio
async def test_document_is_loaded_from_safe_storage_then_uploaded_and_sent(
    monkeypatch,
    tmp_path,
):
    from app.services import outbound_whatsapp as module

    document = tmp_path / "proposal.pdf"
    document.write_bytes(b"synthetic-pdf")
    message, route, connection = _context(
        kind="document",
        payload={
            "storage_key": "blobs/ab/proposal.pdf",
            "name": "proposal.pdf",
            "mime": "application/pdf",
            "caption": "Proposal",
        },
    )
    client = _FakeClient(
        [
            _response(200, {"id": "media.test"}),
            _response(200, {"messages": [{"id": "wamid.document"}]}),
        ]
    )
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(module.document_storage, "path_for", lambda _key: document)
    monkeypatch.setattr(
        module.whatsapp_service,
        "resolve_connection",
        lambda *_args, **_kwargs: SimpleNamespace(
            access_token="must-not-leak",
            phone_number_id="123456789",
        ),
    )

    result = await WhatsAppOutboundAdapter().deliver(
        message=message,
        route=route,
        connection=connection,
    )

    assert result == Accepted("wamid.document")
    assert client.requests[0][0].endswith("/media")
    assert client.requests[1][0].endswith("/messages")
    assert client.requests[1][1]["json"]["document"] == {
        "id": "media.test",
        "caption": "Proposal",
        "filename": "proposal.pdf",
    }


@pytest.mark.asyncio
async def test_unsupported_kind_is_rejected_without_provider_io(monkeypatch):
    from app.services import outbound_whatsapp as module

    message, route, connection = _context(
        kind="template",
        payload={"template_key": "follow_up", "language": "es_AR"},
    )
    monkeypatch.setattr(
        module.whatsapp_service,
        "resolve_connection",
        lambda *_args, **_kwargs: SimpleNamespace(
            access_token="must-not-leak",
            phone_number_id="123456789",
        ),
    )

    result = await WhatsAppOutboundAdapter().deliver(
        message=message,
        route=route,
        connection=connection,
    )

    assert result == Rejected("unsupported_kind")
