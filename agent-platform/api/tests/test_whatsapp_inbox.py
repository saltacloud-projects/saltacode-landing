"""Focused contracts for the durable WhatsApp inbox."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models.whatsapp_inbox import WhatsAppInboundJob
from app.services.agent_runtime import AgentRuntimeUnavailable
from app.services.pipeline import (
    PipelineFinalizationFailed,
    PipelineService,
    WhatsAppDeliveryFailed,
)
from app.services.whatsapp_inbox import minimal_inbound_payload, whatsapp_inbox_worker


def test_minimal_payload_excludes_route_and_credential_material():
    payload = minimal_inbound_payload(
        {
            "phone_number": "5493870000000",
            "content": "hello",
            "message_id": "wamid.test",
            "input_type": "text",
            "audio_media_id": None,
            "interactive_id": None,
            "quoted_id": None,
            "timestamp": "1700000000",
            "access_token": "must-not-persist",
            "app_secret": "must-not-persist",
        }
    )

    assert payload == {
        "phone_number": "5493870000000",
        "content": "hello",
        "input_type": "text",
        "audio_media_id": None,
        "interactive_id": None,
        "quoted_id": None,
    }
    assert "must-not-persist" not in repr(payload)


def test_model_idempotency_is_route_scoped():
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in WhatsAppInboundJob.__table__.constraints
        if constraint.name
    }
    assert unique_constraints["uq_whatsapp_inbound_job_route_message"] == (
        "channel_route_id",
        "provider_message_id",
    )
    connection_column = WhatsAppInboundJob.__table__.c.channel_connection_id
    assert connection_column.nullable is False
    assert next(iter(connection_column.foreign_keys)).target_fullname == (
        "channel_connections.id"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("whatsapp_inbox_poll_seconds", 0),
        ("whatsapp_inbox_stale_seconds", 900),
        ("whatsapp_inbox_max_attempts", 0),
        ("whatsapp_inbox_max_attempts", 21),
    ],
)
def test_worker_settings_reject_unsafe_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(
            postgres_dsn="postgresql+asyncpg://test:test@localhost/test",
            fastapi_api_key="test",
            **{field: value},
        )


def test_default_stale_window_exceeds_maximum_agent_loop():
    configured = Settings(
        postgres_dsn="postgresql+asyncpg://test:test@localhost/test",
        fastapi_api_key="test",
    )
    assert configured.whatsapp_inbox_stale_seconds > 900


def test_compose_pins_single_worker_and_safe_stale_default():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()

    assert "WHATSAPP_INBOX_STALE_SECONDS:-1200" in compose
    worker = compose[compose.index("  whatsapp-worker:") :]
    healthcheck = worker[
        worker.index("    healthcheck:") : worker.index("    depends_on:")
    ]
    assert '"/usr/local/libexec/agent-entrypoint.py"' in healthcheck
    assert '"app.workers.whatsapp_inbox"' in healthcheck
    assert '"--healthcheck"' in healthcheck
    assert "replicas: 1" in worker


def test_only_final_attempt_enables_pipeline_error_notification():
    intermediate = WhatsAppInboundJob(attempts=2, max_attempts=5)
    final = WhatsAppInboundJob(attempts=5, max_attempts=5)

    assert whatsapp_inbox_worker._is_final_attempt(intermediate) is False
    assert whatsapp_inbox_worker._is_final_attempt(final) is True


def test_worker_rejects_route_rebound_to_another_authenticated_connection():
    route_id = uuid4()
    original_connection_id = uuid4()
    job = SimpleNamespace(
        channel_route_id=route_id,
        channel_connection_id=original_connection_id,
    )
    stored_route = SimpleNamespace(
        channel_connection_id=original_connection_id,
    )
    rebound = SimpleNamespace(
        route=SimpleNamespace(id=route_id),
        connection=SimpleNamespace(id=uuid4()),
    )

    with pytest.raises(AgentRuntimeUnavailable, match="connection ownership"):
        whatsapp_inbox_worker._assert_route_ownership(job, stored_route, rebound)


@pytest.mark.asyncio
async def test_durable_pipeline_propagates_meta_send_failure(monkeypatch):
    from app.services import pipeline as module

    send = AsyncMock(return_value=None)
    monkeypatch.setattr(module.whatsapp_service, "send_text_message", send)
    service = PipelineService()

    with pytest.raises(WhatsAppDeliveryFailed):
        await service._send_required_text(
            phone="5493870000000",
            text="hello",
            request_id=str(uuid4()),
            connection=SimpleNamespace(),
            require_accepted=True,
        )
    assert (
        await service._send_required_text(
            phone="5493870000000",
            text="hello",
            request_id=str(uuid4()),
            connection=None,
            require_accepted=False,
        )
        is None
    )


@pytest.mark.asyncio
async def test_durable_pipeline_propagates_final_commit_failure(monkeypatch):
    class FailingDb:
        rolled_back = False

        async def commit(self):
            raise RuntimeError("database unavailable")

        async def rollback(self):
            self.rolled_back = True

    service = PipelineService()
    monkeypatch.setattr(service, "_log_audit", AsyncMock())
    db = FailingDb()

    with pytest.raises(PipelineFinalizationFailed):
        await service._finalize_pipeline(
            db=db,
            redis=None,
            phone="5493870000000",
            content="hello",
            response_text="response",
            request_id=str(uuid4()),
            input_type="text",
            start=0.0,
            intent="agent",
            source_system="dynamic",
            tool_used=None,
            status="success",
            persist_conversation=False,
            raise_on_error=True,
        )
    assert db.rolled_back is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("attempts", "expected"), [(4, False), (5, True)])
async def test_worker_notifies_only_on_the_final_attempt(
    monkeypatch, attempts, expected
):
    from app.services import whatsapp_inbox as module

    job_id = uuid4()
    route_id = uuid4()
    job = WhatsAppInboundJob(
        id=job_id,
        channel_route_id=route_id,
        channel_connection_id=uuid4(),
        provider_message_id="wamid.test",
        payload_json={
            "phone_number": "5493870000000",
            "content": "hello",
            "input_type": "text",
            "audio_media_id": None,
            "interactive_id": None,
            "quoted_id": None,
        },
        status="processing",
        attempts=attempts,
        max_attempts=5,
        locked_by=whatsapp_inbox_worker._worker_id,
    )
    stored_route = SimpleNamespace(
        id=route_id,
        route_key="route-a",
        channel_connection_id=job.channel_connection_id,
    )

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, _statement):
            return SimpleNamespace(one_or_none=lambda: (job, stored_route))

    resolved = SimpleNamespace(
        route=SimpleNamespace(id=route_id, agent_id=uuid4()),
        connection=SimpleNamespace(id=job.channel_connection_id),
    )
    monkeypatch.setattr(module, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(
        module.agent_runtime_resolver,
        "resolve_channel_route",
        AsyncMock(return_value=resolved),
    )
    monkeypatch.setattr(
        module.agent_runtime_resolver,
        "resolve_agent",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        module.whatsapp_service,
        "resolve_connection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    process = AsyncMock()
    monkeypatch.setattr(module.pipeline_service, "process_whatsapp_message", process)

    await whatsapp_inbox_worker._process_job(job_id, redis=object())

    assert process.await_args.kwargs["notify_on_error"] is expected
    assert process.await_args.kwargs["propagate_errors"] is True
