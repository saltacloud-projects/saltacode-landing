"""Focused contracts for provider-neutral durable channel ingress."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.models.channel_inbound import ChannelInboundJob
from app.schemas.inbound import (
    InboundContentType,
    InboundMessageEnvelope,
    InboundRouteContext,
)
from app.services.channel_catalog import resolve_channel_adapter
from app.services.channel_inbound import (
    ChannelInboundService,
    ChannelInboundUnavailable,
    ChannelInboundWorker,
)
from app.services.conversation_control import AutomationBlockedError
from app.services.inbound_crypto import (
    InboundCryptoError,
    InboundPayloadCrypto,
    inbound_payload_crypto,
)
from app.services.pipeline import PipelineService


def _keys(tmp_path, monkeypatch) -> None:
    encryption = tmp_path / "contact.key"
    lookup = tmp_path / "lookup.key"
    encryption.write_bytes(Fernet.generate_key())
    lookup.write_bytes(b"inbound-test-lookup-key-that-is-distinct")
    monkeypatch.setattr(settings, "contact_encryption_key_file", str(encryption))
    monkeypatch.setattr(settings, "contact_lookup_hmac_key_file", str(lookup))


def _message(*, channel: str = "whatsapp") -> InboundMessageEnvelope:
    return InboundMessageEnvelope(
        correlation_id=uuid4(),
        channel=channel,
        route=InboundRouteContext(
            route_key="route-a",
            channel_route_id=uuid4(),
            channel_connection_id=uuid4(),
        ),
        provider_message_id="provider.message",
        provider_thread_id="private-thread",
        provider_sender_id="private-sender",
        content="private content",
        content_type=InboundContentType.TEXT,
        timestamp=datetime.now(timezone.utc),
    )


def test_model_deduplicates_by_route_and_provider_message() -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in ChannelInboundJob.__table__.constraints
        if constraint.name and hasattr(constraint, "columns")
    }
    assert constraints["uq_channel_inbound_job_route_message"] == (
        "channel_route_id",
        "provider_message_id",
    )
    assert "payload_ciphertext" in ChannelInboundJob.__table__.c
    assert "legacy_payload_json" in ChannelInboundJob.__table__.c
    assert "payload_json" not in ChannelInboundJob.__table__.c


def test_payload_crypto_encrypts_and_detects_tampering(tmp_path, monkeypatch) -> None:
    _keys(tmp_path, monkeypatch)
    crypto = InboundPayloadCrypto()
    payload = {"content": "private", "provider_sender_id": "sender"}

    protected = crypto.protect(payload)

    assert "private" not in protected.ciphertext
    assert (
        crypto.reveal(
            ciphertext=protected.ciphertext,
            integrity_hash=protected.integrity_hash,
        )
        == payload
    )
    with pytest.raises(InboundCryptoError, match="integrity"):
        crypto.reveal(
            ciphertext=protected.ciphertext,
            integrity_hash="0" * 64,
        )


def test_thread_key_is_route_scoped_and_non_reversible(tmp_path, monkeypatch) -> None:
    _keys(tmp_path, monkeypatch)
    crypto = InboundPayloadCrypto()
    first = crypto.thread_key(channel="whatsapp", route_id="a", thread_id="secret")
    second = crypto.thread_key(channel="whatsapp", route_id="b", thread_id="secret")

    assert first != second
    assert len(first) == 64
    assert "secret" not in first


@pytest.mark.asyncio
async def test_external_ingress_rejects_web_chat() -> None:
    message = _message(channel="web")
    route = SimpleNamespace(
        id=message.route.channel_route_id,
        channel="web",
        route_key=message.route.route_key,
        channel_connection_id=message.route.channel_connection_id,
        agent_id=uuid4(),
    )
    connection = SimpleNamespace(
        id=message.route.channel_connection_id,
        channel="web",
        adapter_key="web_builtin",
    )

    with pytest.raises(ValueError, match="does not accept web chat"):
        await ChannelInboundService().enqueue_batch(
            SimpleNamespace(),
            messages=[message],
            route=route,
            connection=connection,
            adapter=resolve_channel_adapter(channel="web"),
        )


@pytest.mark.asyncio
async def test_external_ingress_fails_safely_when_payload_key_is_unavailable(
    monkeypatch,
) -> None:
    message = _message()
    route = SimpleNamespace(
        id=message.route.channel_route_id,
        channel="whatsapp",
        route_key=message.route.route_key,
        channel_connection_id=message.route.channel_connection_id,
        agent_id=uuid4(),
        version=0,
    )
    connection = SimpleNamespace(
        id=message.route.channel_connection_id,
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        version=0,
    )

    def fail_to_protect(_payload):
        raise InboundCryptoError("secret detail")

    monkeypatch.setattr(inbound_payload_crypto, "protect", fail_to_protect)

    with pytest.raises(ChannelInboundUnavailable, match="could not be protected"):
        await ChannelInboundService().enqueue_batch(
            SimpleNamespace(),
            messages=[message],
            route=route,
            connection=connection,
            adapter=resolve_channel_adapter(channel="whatsapp"),
        )


def test_worker_rejects_any_route_snapshot_drift() -> None:
    connection_id = uuid4()
    agent_id = uuid4()
    job = SimpleNamespace(
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        adapter_version=1,
        channel_route_version=2,
        route_key_snapshot="route-a",
        channel_connection_id=connection_id,
        channel_connection_version=3,
        routing_agent_id=agent_id,
    )
    route = SimpleNamespace(
        channel="whatsapp",
        version=2,
        route_key="route-a",
        channel_connection_id=connection_id,
        agent_id=agent_id,
        is_active=True,
    )
    connection = SimpleNamespace(
        channel="whatsapp",
        version=4,
        adapter_key="meta_whatsapp_cloud",
        is_active=True,
    )

    with pytest.raises(Exception, match="snapshot changed"):
        ChannelInboundWorker._assert_route_snapshot(
            job,
            route,
            connection,
            resolve_channel_adapter(channel="whatsapp"),
        )


def test_pipeline_has_no_direct_outbound_send_calls_or_pii_log_extras() -> None:
    source = inspect.getsource(PipelineService)
    for method in (
        "send_text_message",
        "send_document_message",
        "send_image_message",
        "upload_media",
        "upload_media_path",
    ):
        assert f".{method}(" not in source
    for forbidden in (
        '"phone":',
        '"content_preview":',
        '"response_preview":',
        '"user_message":',
        '"preview":',
    ):
        assert forbidden not in source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "expected_status", "expected_safe_code"),
    (
        ("claimed", "routed_to_human", "automation_not_owner"),
        (
            "agent_effect_started",
            "review_required",
            "ownership_changed_after_effect",
        ),
    ),
)
async def test_takeover_disposition_depends_on_external_effect_phase(
    monkeypatch,
    phase: str,
    expected_status: str,
    expected_safe_code: str,
) -> None:
    worker = ChannelInboundWorker()
    job_id = uuid4()
    claim = AsyncMock(return_value=job_id)
    process = AsyncMock(side_effect=AutomationBlockedError())
    current_phase = AsyncMock(return_value=phase)
    transition = AsyncMock()
    monkeypatch.setattr(worker, "_claim_job", claim)
    monkeypatch.setattr(worker, "_process_job", process)
    monkeypatch.setattr(worker, "_current_phase", current_phase)
    monkeypatch.setattr(worker, "_transition_owned", transition)

    assert await worker.run_once(object()) is True

    transition.assert_awaited_once_with(
        job_id,
        status=expected_status,
        event_type=expected_status,
        safe_code=expected_safe_code,
    )


def test_whatsapp_worker_module_is_only_a_compatibility_wrapper() -> None:
    from app.workers import channel_inbound, whatsapp_inbox

    assert whatsapp_inbox.main is channel_inbound.main
    assert whatsapp_inbox.check_worker_health is channel_inbound.check_worker_health
