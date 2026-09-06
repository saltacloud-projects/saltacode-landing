"""PostgreSQL integration coverage for durable WhatsApp acceptance and recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.whatsapp_inbox import WhatsAppInboundJob
from app.services.whatsapp_inbox import whatsapp_inbox_service, whatsapp_inbox_worker
from app.workers.whatsapp_inbox import check_worker_health

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


def _message(message_id: str) -> dict:
    return {
        "phone_number": "5493870000000",
        "content": "hello",
        "message_id": message_id,
        "input_type": "text",
        "audio_media_id": None,
        "interactive_id": None,
        "quoted_id": None,
    }


@pytest.mark.asyncio
async def test_duplicate_scope_and_stale_job_recovery() -> None:
    provider_message_id = f"wamid.inbox.{uuid4()}"
    profile_slug = f"inbox-agent-{uuid4().hex}"
    connection_slug = f"inbox-connection-{uuid4().hex}"
    primary_route_key = f"inbox-primary-{uuid4().hex}"
    second_route_key = f"inbox-test-{uuid4().hex}"
    profile_id = None
    connection_id = None
    primary_route_id = None
    second_route_id = None
    job_ids = []
    try:
        async with AsyncSessionLocal() as db:
            profile = AgentProfile(
                name="Inbox integration agent",
                slug=profile_slug,
                version=1,
                is_active=True,
                is_public=False,
                retention_days=30,
                prompt_identity="test",
                prompt_domain="test",
                prompt_guardrails="test",
                unauthorized_message="unauthorized",
                error_message="error",
            )
            connection = ChannelConnection(
                name="Inbox integration connection",
                slug=connection_slug,
                channel="whatsapp",
                external_account_id=f"account-{uuid4().hex}",
                settings_json={},
                is_active=True,
            )
            db.add_all([profile, connection])
            await db.flush()
            primary_route = ChannelAgentRoute(
                channel="whatsapp",
                route_key=primary_route_key,
                channel_connection_id=connection.id,
                agent_id=profile.id,
                is_active=True,
            )
            second_route = ChannelAgentRoute(
                channel="whatsapp",
                route_key=second_route_key,
                channel_connection_id=connection.id,
                agent_id=profile.id,
                is_active=True,
            )
            db.add_all([primary_route, second_route])
            await db.commit()
            profile_id = profile.id
            connection_id = connection.id
            primary_route_id = primary_route.id
            second_route_id = second_route.id

            first = await whatsapp_inbox_service.enqueue(
                db,
                channel_route_id=primary_route_id,
                channel_connection_id=connection_id,
                provider_message_id=provider_message_id,
                message=_message(provider_message_id),
            )
            duplicate = await whatsapp_inbox_service.enqueue(
                db,
                channel_route_id=primary_route_id,
                channel_connection_id=connection_id,
                provider_message_id=provider_message_id,
                message=_message(provider_message_id),
            )
            other_route = await whatsapp_inbox_service.enqueue(
                db,
                channel_route_id=second_route.id,
                channel_connection_id=connection_id,
                provider_message_id=provider_message_id,
                message=_message(provider_message_id),
            )
            assert first.job_id is not None
            assert duplicate.duplicate is True
            assert other_route.job_id is not None
            job_ids = [first.job_id, other_route.job_id]

            first_job = await db.get(WhatsAppInboundJob, first.job_id)
            assert first_job is not None
            first_job.status = "processing"
            first_job.attempts = 1
            first_job.locked_by = "abandoned-worker"
            first_job.locked_at = datetime.now(timezone.utc) - timedelta(hours=1)
            await db.commit()

        async with AsyncSessionLocal() as db:
            claimed_id = await whatsapp_inbox_worker._claim_job(db)
            assert claimed_id == first.job_id

        async with AsyncSessionLocal() as db:
            recovered = await db.get(WhatsAppInboundJob, first.job_id)
            assert recovered is not None
            assert recovered.status == "processing"
            assert recovered.attempts == 2

        await whatsapp_inbox_worker._persist_success(first.job_id)

        async with AsyncSessionLocal() as db:
            completed = await db.get(WhatsAppInboundJob, first.job_id)
            assert completed is not None
            assert completed.status == "completed"
            assert completed.payload_json == {}

            retrying = await db.get(WhatsAppInboundJob, other_route.job_id)
            assert retrying is not None
            retrying.status = "processing"
            retrying.attempts = 1
            retrying.max_attempts = 2
            retrying.locked_by = whatsapp_inbox_worker._worker_id
            retrying.locked_at = datetime.now(timezone.utc)
            await db.commit()

        await whatsapp_inbox_worker._persist_failure(
            other_route.job_id, RuntimeError("first failure")
        )

        async with AsyncSessionLocal() as db:
            retrying = await db.get(WhatsAppInboundJob, other_route.job_id)
            assert retrying is not None
            assert retrying.status == "queued"
            assert retrying.payload_json["content"] == "hello"
            retrying.status = "processing"
            retrying.attempts = retrying.max_attempts
            retrying.locked_by = whatsapp_inbox_worker._worker_id
            retrying.locked_at = datetime.now(timezone.utc)
            await db.commit()

        await whatsapp_inbox_worker._persist_failure(
            other_route.job_id, RuntimeError("final failure")
        )

        async with AsyncSessionLocal() as db:
            failed = await db.get(WhatsAppInboundJob, other_route.job_id)
            assert failed is not None
            assert failed.status == "failed"
            assert failed.payload_json == {}
            assert failed.channel_connection_id == connection_id

        await check_worker_health()
    finally:
        async with AsyncSessionLocal() as db:
            if job_ids:
                await db.execute(
                    delete(WhatsAppInboundJob).where(WhatsAppInboundJob.id.in_(job_ids))
                )
            if second_route_id is not None:
                await db.execute(
                    delete(ChannelAgentRoute).where(
                        ChannelAgentRoute.id.in_(
                            [
                                route_id
                                for route_id in (primary_route_id, second_route_id)
                                if route_id
                            ]
                        )
                    )
                )
            if connection_id is not None:
                await db.execute(
                    delete(ChannelConnection).where(
                        ChannelConnection.id == connection_id
                    )
                )
            if profile_id is not None:
                await db.execute(
                    delete(AgentProfile).where(AgentProfile.id == profile_id)
                )
            await db.commit()
