"""PostgreSQL coverage for the safe outbound delivery review projection."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryEvent,
    OutboundMessage,
)
from app.models.platform import ChatConversation, Principal
from app.schemas.deliveries import DeliveryStatus
from app.services.outbound_delivery_review import (
    DeliveryReviewNotFoundError,
    OutboundDeliveryReviewService,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_review_is_agent_scoped_safe_filterable_and_fifo_aware():
    service = OutboundDeliveryReviewService()
    profile_ids = []
    route_ids = []
    principal_ids = []
    connection_id = None

    try:
        async with AsyncSessionLocal() as db:
            profiles = [
                AgentProfile(
                    name=f"Delivery review agent {label}",
                    slug=f"delivery-review-{label}-{uuid4().hex}",
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
                for label in ("a", "b")
            ]
            connection = ChannelConnection(
                name="Delivery review connection",
                slug=f"delivery-review-connection-{uuid4().hex}",
                channel="whatsapp",
                adapter_key="meta_whatsapp_cloud",
                version=0,
                external_account_id=f"delivery-review-{uuid4().hex}",
                settings_json={},
                is_active=True,
            )
            db.add_all([*profiles, connection])
            await db.flush()
            routes = [
                ChannelAgentRoute(
                    channel="whatsapp",
                    version=0,
                    route_key=f"delivery-review-route-{label}-{uuid4().hex}",
                    channel_connection_id=connection.id,
                    agent_id=profile.id,
                    is_active=True,
                )
                for label, profile in zip(("a", "b"), profiles, strict=True)
            ]
            principals = [
                Principal(display_name=f"Delivery review principal {label}")
                for label in ("a", "b")
            ]
            db.add_all([*routes, *principals])
            await db.flush()
            conversations = [
                ChatConversation(
                    agent_id=profile.id,
                    principal_id=principal.id,
                    channel="whatsapp",
                    external_thread_id=f"delivery-review-thread-{uuid4().hex}",
                    route_key=route.route_key,
                    channel_route_id=route.id,
                    transcript_consent=True,
                    consent_version="test-v1",
                )
                for profile, principal, route in zip(
                    profiles,
                    principals,
                    routes,
                    strict=True,
                )
            ]
            db.add_all(conversations)
            await db.flush()
            unknown = _message(
                conversation=conversations[0],
                route=routes[0],
                sequence=1,
                status="delivery_unknown",
                correlation_id="delivery-review-unknown",
            )
            queued = _message(
                conversation=conversations[0],
                route=routes[0],
                sequence=2,
                status="queued",
                correlation_id="delivery-review-queued",
            )
            failed = _message(
                conversation=conversations[0],
                route=routes[0],
                sequence=3,
                status="failed",
                correlation_id="delivery-review-failed",
            )
            other_agent = _message(
                conversation=conversations[1],
                route=routes[1],
                sequence=1,
                status="failed",
                correlation_id="delivery-review-other-agent",
            )
            db.add_all([unknown, queued, failed, other_agent])
            await db.flush()
            attempt = OutboundAttempt(
                outbound_message_id=unknown.id,
                attempt_number=1,
                worker_id="delivery-review-worker",
                control_version=0,
            )
            db.add(attempt)
            await db.flush()
            db.add(
                OutboundDeliveryEvent(
                    outbound_message_id=unknown.id,
                    attempt_id=attempt.id,
                    event_type="delivery_unknown",
                    from_status="dispatching",
                    to_status="delivery_unknown",
                    actor_type="worker",
                    actor_id="delivery-review-worker",
                    safe_code="provider_timeout",
                )
            )
            await db.commit()

            profile_ids = [profile.id for profile in profiles]
            route_ids = [route.id for route in routes]
            principal_ids = [principal.id for principal in principals]
            connection_id = connection.id
            unknown_id = unknown.id
            queued_id = queued.id
            failed_id = failed.id
            other_id = other_agent.id
            conversation_id = conversations[0].id

        async with AsyncSessionLocal() as db:
            page = await service.list_deliveries(db, agent_id=profile_ids[0])
            assert page.total == 3
            assert [item.id for item in page.items] == [
                unknown_id,
                failed_id,
                queued_id,
            ]
            assert page.items[0].latest_safe_code == "provider_timeout"
            assert page.items[0].attempt_count == 1
            assert page.items[0].is_fifo_blocking is True
            assert page.items[0].blocked_message_count == 1

            filtered = await service.list_deliveries(
                db,
                agent_id=profile_ids[0],
                channel="whatsapp",
                delivery_status=DeliveryStatus.DELIVERY_UNKNOWN,
                conversation_id=conversation_id,
            )
            assert [item.id for item in filtered.items] == [unknown_id]

            detail = await service.get_delivery(
                db,
                agent_id=profile_ids[0],
                delivery_id=unknown_id,
            )
            assert detail.attempts[0].attempt_number == 1
            assert detail.events[0].safe_code == "provider_timeout"
            assert detail.resolution_version == 0
            assert detail.resolution is None
            assert not hasattr(detail, "payload_json")
            assert not hasattr(detail.attempts[0], "worker_id")

            with pytest.raises(DeliveryReviewNotFoundError):
                await service.get_delivery(
                    db,
                    agent_id=profile_ids[0],
                    delivery_id=other_id,
                )
    finally:
        async with AsyncSessionLocal() as db:
            if principal_ids:
                await db.execute(
                    delete(Principal).where(Principal.id.in_(principal_ids))
                )
            if route_ids:
                await db.execute(
                    delete(ChannelAgentRoute).where(ChannelAgentRoute.id.in_(route_ids))
                )
            if connection_id is not None:
                await db.execute(
                    delete(ChannelConnection).where(
                        ChannelConnection.id == connection_id
                    )
                )
            if profile_ids:
                await db.execute(
                    delete(AgentProfile).where(AgentProfile.id.in_(profile_ids))
                )
            await db.commit()


def _message(
    *,
    conversation: ChatConversation,
    route: ChannelAgentRoute,
    sequence: int,
    status: str,
    correlation_id: str,
) -> OutboundMessage:
    return OutboundMessage(
        conversation_id=conversation.id,
        agent_id=conversation.agent_id,
        channel_route_id=route.id,
        channel=route.channel,
        adapter_key="meta_whatsapp_cloud",
        channel_connection_id=route.channel_connection_id,
        route_version=route.version,
        connection_version=0,
        chat_message_id=None,
        kind="text",
        payload_json={"text": "Sensitive body excluded from review"},
        destination="sensitive-destination",
        sender_type="automation",
        sender_admin_id=None,
        control_version=0,
        sequence=sequence,
        idempotency_key=f"delivery-review-{uuid4().hex}",
        payload_hash="a" * 64,
        correlation_id=correlation_id,
        status=status,
        last_attempt_number=1 if status == "delivery_unknown" else 0,
    )
