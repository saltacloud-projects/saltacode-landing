"""PostgreSQL coverage for durable provider-neutral channel ingress."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.channel_inbound import ChannelInboundEvent, ChannelInboundJob
from app.schemas.inbound import (
    InboundContentType,
    InboundMessageEnvelope,
    InboundRouteContext,
)
from app.services.channel_catalog import resolve_channel_adapter
from app.services.channel_inbound import (
    ChannelInboundWorker,
    channel_inbound_service,
    channel_inbound_worker,
)
from app.services.channel_inbound_review import (
    ChannelInboundIdempotencyConflict,
    ChannelInboundNotFound,
    channel_inbound_review_service,
)
from app.workers.channel_inbound import check_worker_health

pytestmark = pytest.mark.integration


def _profile() -> AgentProfile:
    return AgentProfile(
        name="Inbound integration",
        slug=f"inbound-{uuid4().hex}",
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


def _message(route, connection, message_id: str, thread: str):
    return InboundMessageEnvelope(
        correlation_id=uuid4(),
        channel="whatsapp",
        route=InboundRouteContext(
            route_key=route.route_key,
            channel_route_id=route.id,
            channel_connection_id=connection.id,
        ),
        provider_message_id=message_id,
        provider_thread_id=thread,
        provider_sender_id=thread,
        content="sensitive body",
        content_type=InboundContentType.TEXT,
        timestamp=datetime.now(timezone.utc),
    )


def _set_crypto_keys(tmp_path, monkeypatch, *, prefix: str) -> None:
    encryption = tmp_path / f"{prefix}-contact.key"
    lookup = tmp_path / f"{prefix}-lookup.key"
    encryption.write_bytes(Fernet.generate_key())
    lookup.write_bytes(f"{prefix}-lookup-key-distinct-material".encode())
    monkeypatch.setattr(settings, "contact_encryption_key_file", str(encryption))
    monkeypatch.setattr(settings, "contact_lookup_hmac_key_file", str(lookup))


@pytest.mark.asyncio
async def test_encrypted_dedupe_fifo_and_stale_lease(tmp_path, monkeypatch) -> None:
    _set_crypto_keys(tmp_path, monkeypatch, prefix="integration")

    ids: dict[str, object] = {}
    try:
        async with AsyncSessionLocal() as db:
            profile = _profile()
            connection = ChannelConnection(
                name="Inbound WhatsApp",
                slug=f"inbound-wa-{uuid4().hex}",
                channel="whatsapp",
                adapter_key="meta_whatsapp_cloud",
                version=0,
                external_account_id=str(uuid4().int)[:15],
                settings_json={},
                encrypted_credentials=None,
                is_active=True,
            )
            db.add_all([profile, connection])
            await db.flush()
            route = ChannelAgentRoute(
                channel="whatsapp",
                version=0,
                route_key=f"inbound-{uuid4().hex}",
                channel_connection_id=connection.id,
                agent_id=profile.id,
                is_active=True,
            )
            db.add(route)
            await db.commit()
            ids.update(profile=profile.id, connection=connection.id, route=route.id)

            first_message = _message(route, connection, "message-1", "thread-a")
            second_message = _message(route, connection, "message-2", "thread-a")
            other_message = _message(route, connection, "message-3", "thread-b")
            accepted = await channel_inbound_service.enqueue_batch(
                db,
                messages=[first_message, second_message, other_message],
                route=route,
                connection=connection,
                adapter=resolve_channel_adapter(channel="whatsapp"),
            )
            duplicate = await channel_inbound_service.enqueue_batch(
                db,
                messages=[first_message],
                route=route,
                connection=connection,
                adapter=resolve_channel_adapter(channel="whatsapp"),
            )
            assert len(accepted.accepted_job_ids) == 3
            assert duplicate.duplicate_count == 1
            ids["jobs"] = accepted.accepted_job_ids

            first = await db.get(ChannelInboundJob, accepted.accepted_job_ids[0])
            second = await db.get(ChannelInboundJob, accepted.accepted_job_ids[1])
            other = await db.get(ChannelInboundJob, accepted.accepted_job_ids[2])
            assert first is not None
            assert second is not None
            assert other is not None
            assert first.legacy_payload_json is None
            assert "sensitive body" not in (first.payload_ciphertext or "")
            assert first.payload_hash is not None
            assert first.thread_key is not None
            ordered_at = datetime.now(timezone.utc)
            first.created_at = ordered_at
            second.created_at = ordered_at + timedelta(seconds=1)
            other.created_at = ordered_at + timedelta(seconds=2)
            await db.commit()

        workers = (ChannelInboundWorker(), ChannelInboundWorker())
        claims = await asyncio.gather(*(_claim_once(worker) for worker in workers))
        assert set(claims) == {
            accepted.accepted_job_ids[0],
            accepted.accepted_job_ids[2],
        }
        for worker, claimed in zip(workers, claims, strict=True):
            assert claimed is not None
            if claimed == accepted.accepted_job_ids[0]:
                await worker._transition_owned(
                    claimed,
                    status="review_required",
                    event_type="review_required",
                    safe_code="test_review",
                )
            else:
                await worker._transition_owned(
                    claimed,
                    status="completed",
                    event_type="completed",
                )

        async with AsyncSessionLocal() as db:
            blocked = await db.get(ChannelInboundJob, accepted.accepted_job_ids[1])
            stale = await db.get(ChannelInboundJob, accepted.accepted_job_ids[0])
            assert blocked is not None and blocked.status == "queued"
            assert stale is not None
            stale.status = "processing"
            stale.lease_owner = "dead-worker"
            stale.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db.commit()

        async with AsyncSessionLocal() as db:
            assert await channel_inbound_worker._claim_job(db) is None
        async with AsyncSessionLocal() as db:
            stale = await db.get(ChannelInboundJob, accepted.accepted_job_ids[0])
            assert stale is not None
            assert stale.status == "review_required"
            assert stale.safe_code == "lease_expired"
            events = (
                (
                    await db.execute(
                        select(ChannelInboundEvent).where(
                            ChannelInboundEvent.job_id == stale.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [event.state_version for event in events] == sorted(
                event.state_version for event in events
            )
        await check_worker_health()
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_legacy_review_requeue_encrypts_payload_and_is_agent_scoped(
    tmp_path, monkeypatch
) -> None:
    _set_crypto_keys(tmp_path, monkeypatch, prefix="legacy-review")

    ids: dict[str, object] = {}
    try:
        async with AsyncSessionLocal() as db:
            profile = _profile()
            admin = AdminUser(
                email=f"inbound-review-{uuid4().hex}@example.test",
                hashed_password="not-used",
                name="Inbound review",
                role="admin",
                is_active=True,
                must_change_password=False,
            )
            connection = ChannelConnection(
                name="Legacy review WhatsApp",
                slug=f"legacy-review-wa-{uuid4().hex}",
                channel="whatsapp",
                adapter_key="meta_whatsapp_cloud",
                version=0,
                external_account_id=str(uuid4().int)[:15],
                settings_json={},
                encrypted_credentials=None,
                is_active=True,
            )
            db.add_all([profile, admin, connection])
            await db.flush()
            route = ChannelAgentRoute(
                channel="whatsapp",
                version=0,
                route_key=f"legacy-review-{uuid4().hex}",
                channel_connection_id=connection.id,
                agent_id=profile.id,
                is_active=True,
            )
            db.add(route)
            await db.flush()
            job = ChannelInboundJob(
                channel="whatsapp",
                adapter_key="meta_whatsapp_cloud",
                adapter_version=1,
                channel_route_id=route.id,
                channel_route_version=route.version,
                route_key_snapshot=route.route_key,
                channel_connection_id=connection.id,
                channel_connection_version=connection.version,
                routing_agent_id=profile.id,
                provider_message_id=f"legacy-review-{uuid4().hex}",
                legacy_payload_json={
                    "phone_number": "5493870000000",
                    "content": "legacy private content",
                    "input_type": "text",
                },
                status="review_required",
                phase="legacy_quarantined",
                state_version=0,
                attempts=0,
                legacy_max_attempts=5,
                legacy_status="queued",
                safe_code="legacy_payload_quarantined",
            )
            db.add(job)
            await db.flush()
            db.add(_legacy_quarantined_event(job))
            await db.commit()
            ids.update(
                profile=profile.id,
                admin=admin.id,
                connection=connection.id,
                route=route.id,
                job=job.id,
            )

        async with AsyncSessionLocal() as db:
            requeued = await channel_inbound_review_service.requeue(
                db,
                agent_id=ids["profile"],
                job_id=ids["job"],
                admin_id=ids["admin"],
                expected_version=0,
                correlation_id="legacy-review",
                idempotency_key="legacy-review",
            )
            await db.commit()
            assert requeued.status == "queued"
            assert requeued.phase == "accepted"
            assert requeued.state_version == 1
            assert requeued.legacy_payload_json is None
            assert "legacy private content" not in (requeued.payload_ciphertext or "")
            assert requeued.payload_hash is not None
            assert requeued.thread_key is not None

            timeline = await channel_inbound_review_service.timeline(
                db,
                agent_id=ids["profile"],
                job_id=ids["job"],
            )
            assert timeline[-1].has_actor_admin is True

        async with AsyncSessionLocal() as db:
            replayed = await channel_inbound_review_service.requeue(
                db,
                agent_id=ids["profile"],
                job_id=ids["job"],
                admin_id=ids["admin"],
                expected_version=0,
                correlation_id="legacy-review-replay",
                idempotency_key="legacy-review",
            )
            assert replayed.state_version == 1
            with pytest.raises(ChannelInboundIdempotencyConflict):
                await channel_inbound_review_service.cancel(
                    db,
                    agent_id=ids["profile"],
                    job_id=ids["job"],
                    admin_id=ids["admin"],
                    expected_version=1,
                    correlation_id="legacy-review-collision",
                    idempotency_key="legacy-review",
                )
            with pytest.raises(ChannelInboundNotFound):
                await channel_inbound_review_service.get_job(
                    db,
                    agent_id=uuid4(),
                    job_id=ids["job"],
                )
    finally:
        await _cleanup(ids)


def _legacy_quarantined_event(job: ChannelInboundJob) -> ChannelInboundEvent:
    return ChannelInboundEvent(
        job_id=job.id,
        event_type="legacy_quarantined",
        from_status="queued",
        to_status="review_required",
        state_version=0,
        phase="legacy_quarantined",
        actor_type="system",
        safe_code="legacy_payload_quarantined",
        channel=job.channel,
        adapter_key=job.adapter_key,
        adapter_version=job.adapter_version,
        channel_route_id=job.channel_route_id,
        channel_route_version=job.channel_route_version,
        channel_connection_id=job.channel_connection_id,
        channel_connection_version=job.channel_connection_version,
        routing_agent_id=job.routing_agent_id,
        evidence_json={},
    )


async def _claim_once(worker: ChannelInboundWorker):
    async with AsyncSessionLocal() as db:
        return await worker._claim_job(db)


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        job_ids = ids.get("jobs") or ([ids["job"]] if ids.get("job") else [])
        if job_ids:
            await db.execute(
                delete(ChannelInboundEvent).where(
                    ChannelInboundEvent.job_id.in_(job_ids)
                )
            )
            await db.execute(
                delete(ChannelInboundJob).where(ChannelInboundJob.id.in_(job_ids))
            )
        if ids.get("route"):
            await db.execute(
                delete(ChannelAgentRoute).where(ChannelAgentRoute.id == ids["route"])
            )
        if ids.get("connection"):
            await db.execute(
                delete(ChannelConnection).where(
                    ChannelConnection.id == ids["connection"]
                )
            )
        if ids.get("admin"):
            await db.execute(delete(AdminUser).where(AdminUser.id == ids["admin"]))
        if ids.get("profile"):
            await db.execute(
                delete(AgentProfile).where(AgentProfile.id == ids["profile"])
            )
        await db.commit()
