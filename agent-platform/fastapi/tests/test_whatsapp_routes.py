"""Route-scoped WhatsApp ingress and runtime propagation tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.dependencies import get_db
from app.routers import webhooks
from app.services.whatsapp import WhatsAppConnectionContext


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _payload(account_id: str, message_id: str) -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": account_id},
                                "messages": [
                                    {
                                        "from": "5493870000000",
                                        "id": message_id,
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def _status_payload(account_id: str, message_id: str) -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": account_id},
                                "statuses": [
                                    {
                                        "id": message_id,
                                        "recipient_id": "5493870000000",
                                        "status": "delivered",
                                        "timestamp": "1700000000",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


@pytest.fixture
def route_app():
    app = FastAPI()
    app.include_router(webhooks.router, prefix="/webhooks")

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    return app


def _resolved(label: str):
    runtime = SimpleNamespace(profile=SimpleNamespace(id=uuid4(), slug=label))
    return SimpleNamespace(
        route=SimpleNamespace(id=uuid4(), agent_id=runtime.profile.id),
        connection=SimpleNamespace(),
        runtime=runtime,
    )


def _connection(label: str) -> WhatsAppConnectionContext:
    return WhatsAppConnectionContext(
        connection_id=uuid4(),
        phone_number_id=f"account-{label}",
        access_token=f"access-{label}",
        verify_token=f"verify-{label}",
        app_secret=f"secret-{label}",
        route_key=f"route-{label}",
    )


@pytest.mark.asyncio
async def test_routes_isolate_runtime_and_connection(route_app, monkeypatch):
    resolved = {"route-a": _resolved("agent-a"), "route-b": _resolved("agent-b")}
    connections = {"route-a": _connection("a"), "route-b": _connection("b")}

    async def resolve_channel_route(_db, _channel, route_key):
        return resolved[route_key]

    async def resolve_agent(_db, agent_id, *, require_public):
        assert require_public is False
        return next(
            item.runtime
            for item in resolved.values()
            if item.route.agent_id == agent_id
        )

    monkeypatch.setattr(
        webhooks.agent_runtime_resolver,
        "resolve_channel_route",
        resolve_channel_route,
    )
    monkeypatch.setattr(webhooks.agent_runtime_resolver, "resolve_agent", resolve_agent)
    monkeypatch.setattr(
        webhooks.whatsapp_service,
        "resolve_connection",
        lambda _connection_row, *, route_key: connections[route_key],
    )
    process = AsyncMock()
    monkeypatch.setattr(webhooks.pipeline_service, "process_whatsapp_message", process)

    transport = httpx.ASGITransport(app=route_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for label in ("a", "b"):
            body = _payload(f"account-{label}", f"wamid.{label}")
            response = await client.post(
                f"/webhooks/whatsapp/route-{label}",
                content=body,
                headers={"X-Hub-Signature-256": _signature(body, f"secret-{label}")},
            )
            assert response.status_code == 200
        await asyncio.sleep(0)

    assert process.await_count == 2
    first, second = process.await_args_list
    assert first.kwargs["resolved_runtime"] is resolved["route-a"].runtime
    assert first.kwargs["whatsapp_connection"] is connections["route-a"]
    assert first.kwargs["channel_route_id"] == resolved["route-a"].route.id
    assert second.kwargs["resolved_runtime"] is resolved["route-b"].runtime
    assert second.kwargs["whatsapp_connection"] is connections["route-b"]
    assert first.kwargs["resolved_runtime"] is not second.kwargs["resolved_runtime"]


@pytest.mark.asyncio
async def test_route_rejects_wrong_signature_before_processing(route_app, monkeypatch):
    resolved = _resolved("agent-a")
    connection = _connection("a")
    monkeypatch.setattr(
        webhooks.agent_runtime_resolver,
        "resolve_channel_route",
        AsyncMock(return_value=resolved),
    )
    resolve_agent = AsyncMock(return_value=resolved.runtime)
    monkeypatch.setattr(webhooks.agent_runtime_resolver, "resolve_agent", resolve_agent)
    monkeypatch.setattr(
        webhooks.whatsapp_service,
        "resolve_connection",
        lambda _row, *, route_key: connection,
    )
    process = AsyncMock()
    monkeypatch.setattr(webhooks.pipeline_service, "process_whatsapp_message", process)
    body = b"{not-json"

    transport = httpx.ASGITransport(app=route_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/whatsapp/route-a",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body, "wrong-secret")},
        )

    assert response.status_code == 401
    process.assert_not_awaited()
    resolve_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_rejects_wrong_account_before_processing(route_app, monkeypatch):
    resolved = _resolved("agent-a")
    connection = _connection("a")
    monkeypatch.setattr(
        webhooks.agent_runtime_resolver,
        "resolve_channel_route",
        AsyncMock(return_value=resolved),
    )
    resolve_agent = AsyncMock(return_value=resolved.runtime)
    monkeypatch.setattr(webhooks.agent_runtime_resolver, "resolve_agent", resolve_agent)
    monkeypatch.setattr(
        webhooks.whatsapp_service,
        "resolve_connection",
        lambda _row, *, route_key: connection,
    )
    process = AsyncMock()
    monkeypatch.setattr(webhooks.pipeline_service, "process_whatsapp_message", process)
    body = _payload("another-account", "wamid.a")

    transport = httpx.ASGITransport(app=route_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/whatsapp/route-a",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body, "secret-a")},
        )

    assert response.status_code == 403
    process.assert_not_awaited()
    resolve_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_verification_uses_connection_token(route_app, monkeypatch):
    resolved = _resolved("agent-a")
    connection = _connection("a")
    monkeypatch.setattr(
        webhooks.agent_runtime_resolver,
        "resolve_channel_route",
        AsyncMock(return_value=resolved),
    )
    resolve_agent = AsyncMock(return_value=resolved.runtime)
    monkeypatch.setattr(webhooks.agent_runtime_resolver, "resolve_agent", resolve_agent)
    monkeypatch.setattr(
        webhooks.whatsapp_service,
        "resolve_connection",
        lambda _row, *, route_key: connection,
    )

    transport = httpx.ASGITransport(app=route_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.get(
            "/webhooks/whatsapp/route-a",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-a",
                "hub.challenge": "challenge",
            },
        )
        rejected = await client.get(
            "/webhooks/whatsapp/route-a",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-b",
                "hub.challenge": "challenge",
            },
        )

    assert ok.status_code == 200
    assert ok.text == "challenge"
    assert rejected.status_code == 403
    resolve_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_status_event_does_not_resolve_agent_runtime(
    route_app, monkeypatch
):
    from app.services import delivery_status

    resolved = _resolved("agent-a")
    connection = _connection("a")
    monkeypatch.setattr(
        webhooks.agent_runtime_resolver,
        "resolve_channel_route",
        AsyncMock(return_value=resolved),
    )
    resolve_agent = AsyncMock(side_effect=AssertionError("runtime must stay lazy"))
    monkeypatch.setattr(webhooks.agent_runtime_resolver, "resolve_agent", resolve_agent)
    monkeypatch.setattr(
        webhooks.whatsapp_service,
        "resolve_connection",
        lambda _row, *, route_key: connection,
    )
    upsert = AsyncMock()
    monkeypatch.setattr(delivery_status, "upsert_statuses", upsert)
    body = _status_payload("account-a", "wamid.status")

    transport = httpx.ASGITransport(app=route_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/whatsapp/route-a",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body, "secret-a")},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "status_recorded"}
    resolve_agent.assert_not_awaited()
    upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_transcription_uses_resolved_provider_and_runtime_model(monkeypatch):
    from app.services import transcription as module

    create = AsyncMock(return_value="transcript")
    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    )
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(module, "AsyncOpenAI", factory)
    runtime = SimpleNamespace(
        api_key="provider-secret",
        provider=SimpleNamespace(base_url="https://provider.example/v1"),
        config=SimpleNamespace(transcription_model="transcription-agent-a"),
    )

    result = await module.TranscriptionService().transcribe(b"audio", runtime=runtime)

    assert result == "transcript"
    factory.assert_called_once_with(
        api_key="provider-secret", base_url="https://provider.example/v1"
    )
    assert create.await_args.kwargs["model"] == "transcription-agent-a"


def test_connection_context_repr_excludes_plaintext_secrets():
    connection = _connection("a")
    rendered = repr(connection)
    assert "access-a" not in rendered
    assert "verify-a" not in rendered
    assert "secret-a" not in rendered


def test_persisted_connection_is_decrypted_and_validated_request_scoped(monkeypatch):
    from app.services import whatsapp as module

    row = SimpleNamespace(
        id=uuid4(),
        channel="whatsapp",
        is_active=True,
        external_account_id="account-a",
        encrypted_credentials="ciphertext",
    )
    decrypt = MagicMock(
        return_value={
            "access_token": "access-a",
            "verify_token": "verify-a",
            "app_secret": "secret-a",
        }
    )
    monkeypatch.setattr(module.credential_cipher, "decrypt", decrypt)

    context = module.WhatsAppService().resolve_connection(row, route_key="route-a")

    decrypt.assert_called_once_with("ciphertext")
    assert context.connection_id == row.id
    assert context.phone_number_id == "account-a"
    assert context.route_key == "route-a"


@pytest.mark.asyncio
async def test_delivery_uses_resolved_connection_instead_of_environment(monkeypatch):
    from app.services import whatsapp as module

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.status_code = 200
    response.json.return_value = {"messages": [{"id": "wamid.sent"}]}
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    monkeypatch.setattr(module.httpx, "AsyncClient", MagicMock(return_value=client))
    monkeypatch.setattr(module.settings, "whatsapp_token", "legacy-token")
    monkeypatch.setattr(module.settings, "whatsapp_phone_number_id", "legacy-account")

    message_id = await module.WhatsAppService().send_text_message(
        "5493870000000", "hello", connection=_connection("a")
    )

    assert message_id == "wamid.sent"
    request = client.post.await_args
    assert request.args[0].endswith("/account-a/messages")
    assert request.kwargs["headers"]["Authorization"] == "Bearer access-a"
