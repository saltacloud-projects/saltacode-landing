"""Focused contracts for channel-neutral inbound normalization and access."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.inbound import (
    InboundContentType,
    InboundMessageEnvelope,
    InboundReplyContext,
    InboundRouteContext,
)
from app.services.inbound import (
    InboundAccessDenied,
    InboundAccessPolicy,
    dump_inbound_payload,
    load_inbound_payload,
)


def _route() -> InboundRouteContext:
    return InboundRouteContext(
        route_key="sales-main",
        channel_route_id=uuid4(),
        channel_connection_id=uuid4(),
    )


def _message(route: InboundRouteContext) -> InboundMessageEnvelope:
    return InboundMessageEnvelope(
        correlation_id=uuid4(),
        channel="whatsapp",
        route=route,
        provider_message_id="wamid.message",
        provider_thread_id="5493870000000",
        provider_sender_id="5493870000000",
        content="hello",
        content_type=InboundContentType.TEXT,
        timestamp=datetime(2026, 9, 6, tzinfo=timezone.utc),
        reply_context=InboundReplyContext(provider_message_id="wamid.quoted"),
    )


def test_envelope_is_immutable_and_rejects_unsafe_reply_identifiers() -> None:
    message = _message(_route())

    with pytest.raises(ValidationError):
        message.content = "changed"
    with pytest.raises(ValidationError):
        InboundReplyContext(provider_message_id="unsafe\nidentifier")


def test_persisted_payload_is_versioned_minimal_and_round_trips() -> None:
    message = _message(_route())

    payload = dump_inbound_payload(message)

    assert payload["schema_version"] == "1"
    assert payload["correlation_id"] == str(message.correlation_id)
    assert payload["reply_context"] == {"provider_message_id": "wamid.quoted"}
    assert "provider_message_id" not in payload
    assert "route" not in payload
    assert "channel_route_id" not in payload
    restored = load_inbound_payload(
        payload,
        channel="whatsapp",
        route_key=message.route.route_key,
        channel_route_id=message.route.channel_route_id,
        channel_connection_id=message.route.channel_connection_id,
        provider_message_id=message.provider_message_id,
        fallback_correlation_id=uuid4(),
        fallback_timestamp=datetime.now(timezone.utc),
    )
    assert restored == message


def test_legacy_job_payload_is_upgraded_without_rewriting_it() -> None:
    route = _route()
    correlation_id = uuid4()
    created_at = datetime(2026, 9, 6, tzinfo=timezone.utc)

    restored = load_inbound_payload(
        {
            "phone_number": "5493870000000",
            "content": "legacy",
            "input_type": "audio",
            "audio_media_id": "media-1",
            "interactive_id": None,
            "quoted_id": "wamid.quoted",
        },
        channel="whatsapp",
        route_key=route.route_key,
        channel_route_id=route.channel_route_id,
        channel_connection_id=route.channel_connection_id,
        provider_message_id="wamid.legacy",
        fallback_correlation_id=correlation_id,
        fallback_timestamp=created_at,
    )

    assert restored.correlation_id == correlation_id
    assert restored.provider_thread_id == "5493870000000"
    assert restored.content_type == InboundContentType.AUDIO
    assert restored.provider_media_id == "media-1"
    assert restored.reply_context == InboundReplyContext(
        provider_message_id="wamid.quoted"
    )


@pytest.mark.asyncio
async def test_public_agent_uses_provisional_conversation_identity(monkeypatch) -> None:
    from app.services import inbound as module

    principal_id = uuid4()
    check_access = AsyncMock()
    monkeypatch.setattr(module.governance_service, "check_access", check_access)

    identity = await InboundAccessPolicy().resolve(
        SimpleNamespace(),
        profile=SimpleNamespace(id=uuid4(), is_public=True),
        conversation=SimpleNamespace(principal_id=principal_id),
        sender_id="5493870000000",
        request_id=str(uuid4()),
        channel="whatsapp",
    )

    assert identity.principal_id == principal_id
    assert identity.user_id is None
    assert identity.display_name is None
    check_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_agent_keeps_agent_scoped_whitelist(monkeypatch) -> None:
    from app.services import inbound as module

    check_access = AsyncMock(
        return_value=SimpleNamespace(
            allowed=False,
            reason="not allowed",
            user=None,
        )
    )
    monkeypatch.setattr(module.governance_service, "check_access", check_access)
    profile_id = uuid4()

    with pytest.raises(InboundAccessDenied, match="not allowed"):
        await InboundAccessPolicy().resolve(
            SimpleNamespace(),
            profile=SimpleNamespace(id=profile_id, is_public=False),
            conversation=SimpleNamespace(principal_id=uuid4()),
            sender_id="5493870000000",
            request_id=str(uuid4()),
            channel="whatsapp",
        )

    request = check_access.await_args.args[1]
    assert request.agent_id == profile_id
    assert request.channel == "whatsapp"
