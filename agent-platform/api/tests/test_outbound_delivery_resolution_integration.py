"""PostgreSQL coverage for fail-closed delivery uncertainty resolution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal, engine
from app.core.delivery_resolution import (
    DeliveryEvidenceSource,
    DeliveryNotDeliveredReason,
    DeliveryResolutionAction,
)
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryResolution,
    OutboundMessage,
)
from app.models.platform import ChatConversation, Principal
from app.services.outbound_delivery import OutboundDeliveryService
from app.services.outbound_delivery_resolution import (
    DeliveryResolutionIdempotencyConflictError,
    DeliveryResolutionNotFoundError,
    DeliveryResolutionVersionConflictError,
    OutboundDeliveryResolutionService,
)
from app.services.outbound_delivery_review import OutboundDeliveryReviewService

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _ResolutionGraph:
    agent_id: UUID
    admin_id: UUID
    connection_id: UUID
    route_id: UUID
    principal_id: UUID
    conversation_id: UUID
    unknown_id: UUID
    queued_id: UUID


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def resolution_graph():
    graph = await _create_graph()
    try:
        yield graph
    finally:
        await _cleanup_graph(graph)


@pytest.mark.asyncio
async def test_confirm_delivered_is_idempotent_scoped_and_unlocks_fifo(
    resolution_graph: _ResolutionGraph,
) -> None:
    service = OutboundDeliveryResolutionService()
    async with AsyncSessionLocal() as db:
        with pytest.raises(DeliveryResolutionNotFoundError):
            await service.resolve(
                db,
                agent_id=uuid4(),
                delivery_id=resolution_graph.unknown_id,
                admin_id=resolution_graph.admin_id,
                action=DeliveryResolutionAction.CONFIRM_DELIVERED,
                expected_resolution_version=0,
                provider_message_id="provider-confirmed-123456",
                evidence_source=DeliveryEvidenceSource.PROVIDER_API,
                reason_code=None,
                idempotency_key="resolve-delivered",
                correlation_id="resolution-scope",
            )

        result = await service.resolve(
            db,
            agent_id=resolution_graph.agent_id,
            delivery_id=resolution_graph.unknown_id,
            admin_id=resolution_graph.admin_id,
            action=DeliveryResolutionAction.CONFIRM_DELIVERED,
            expected_resolution_version=0,
            provider_message_id="provider-confirmed-123456",
            evidence_source=DeliveryEvidenceSource.PROVIDER_API,
            reason_code=None,
            idempotency_key="resolve-delivered",
            correlation_id="resolution-applied",
        )
        await db.commit()
        assert result.applied is True
        assert result.message.status == "delivered"
        assert result.message.resolution_version == 1
        assert result.message.last_attempt_number == 0
        assert result.resolution.provider_message_suffix == "123456"
        assert result.resolution.provider_message_hash != "provider-confirmed-123456"

    async with AsyncSessionLocal() as db:
        replay = await service.resolve(
            db,
            agent_id=resolution_graph.agent_id,
            delivery_id=resolution_graph.unknown_id,
            admin_id=resolution_graph.admin_id,
            action=DeliveryResolutionAction.CONFIRM_DELIVERED,
            expected_resolution_version=0,
            provider_message_id="provider-confirmed-123456",
            evidence_source=DeliveryEvidenceSource.PROVIDER_API,
            reason_code=None,
            idempotency_key="resolve-delivered",
            correlation_id="resolution-replay",
        )
        assert replay.applied is False
        with pytest.raises(DeliveryResolutionIdempotencyConflictError):
            await service.resolve(
                db,
                agent_id=resolution_graph.agent_id,
                delivery_id=resolution_graph.unknown_id,
                admin_id=resolution_graph.admin_id,
                action=DeliveryResolutionAction.CONFIRM_DELIVERED,
                expected_resolution_version=0,
                provider_message_id="different-provider-reference",
                evidence_source=DeliveryEvidenceSource.PROVIDER_CONSOLE,
                reason_code=None,
                idempotency_key="resolve-delivered",
                correlation_id="resolution-collision",
            )
        with pytest.raises(DeliveryResolutionVersionConflictError):
            await service.resolve(
                db,
                agent_id=resolution_graph.agent_id,
                delivery_id=resolution_graph.unknown_id,
                admin_id=resolution_graph.admin_id,
                action=DeliveryResolutionAction.CONFIRM_DELIVERED,
                expected_resolution_version=0,
                provider_message_id="provider-confirmed-123456",
                evidence_source=DeliveryEvidenceSource.PROVIDER_API,
                reason_code=None,
                idempotency_key="new-stale-command",
                correlation_id="resolution-stale",
            )

        detail = await OutboundDeliveryReviewService().get_delivery(
            db,
            agent_id=resolution_graph.agent_id,
            delivery_id=resolution_graph.unknown_id,
        )
        assert detail.resolution_version == 1
        assert detail.resolution is not None
        assert detail.resolution.action == "confirm_delivered"
        assert detail.resolution.provider_reference == "…123456"
        assert detail.resolution.has_actor_admin is True
        assert not hasattr(detail.resolution, "actor_admin_id")

    async with AsyncSessionLocal() as db:
        claimed = await OutboundDeliveryService().claim_next(
            db,
            worker_id="resolution-worker",
            stale_before=datetime.now(UTC) - timedelta(minutes=5),
        )
        assert claimed is not None
        assert claimed.message.id == resolution_graph.queued_id


@pytest.mark.asyncio
async def test_concurrent_non_delivery_resolution_applies_once_without_attempt(
    resolution_graph: _ResolutionGraph,
) -> None:
    async def resolve(key: str):
        async with AsyncSessionLocal() as db:
            try:
                result = await OutboundDeliveryResolutionService().resolve(
                    db,
                    agent_id=resolution_graph.agent_id,
                    delivery_id=resolution_graph.unknown_id,
                    admin_id=resolution_graph.admin_id,
                    action=DeliveryResolutionAction.CONFIRM_NOT_DELIVERED,
                    expected_resolution_version=0,
                    provider_message_id=None,
                    evidence_source=None,
                    reason_code=(DeliveryNotDeliveredReason.PROVIDER_RECORD_NOT_FOUND),
                    idempotency_key=key,
                    correlation_id=key,
                )
                await db.commit()
                return result
            except DeliveryResolutionVersionConflictError as exc:
                await db.rollback()
                return exc

    outcomes = await asyncio.gather(resolve("resolution-a"), resolve("resolution-b"))
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert (
        sum(
            isinstance(outcome, DeliveryResolutionVersionConflictError)
            for outcome in outcomes
        )
        == 1
    )

    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, resolution_graph.unknown_id)
        assert message is not None
        assert message.status == "cancelled"
        assert message.resolution_version == 1
        assert message.last_attempt_number == 0
        resolution_count = (
            await db.execute(
                select(func.count(OutboundDeliveryResolution.id)).where(
                    OutboundDeliveryResolution.outbound_message_id == message.id
                )
            )
        ).scalar_one()
        attempt_count = (
            await db.execute(
                select(func.count(OutboundAttempt.id)).where(
                    OutboundAttempt.outbound_message_id == message.id
                )
            )
        ).scalar_one()
        assert resolution_count == 1
        assert attempt_count == 0


async def _create_graph() -> _ResolutionGraph:
    async with AsyncSessionLocal() as db:
        admin = (
            (await db.execute(select(AdminUser).where(AdminUser.is_active.is_(True))))
            .scalars()
            .first()
        )
        assert admin is not None
        agent = AgentProfile(
            name="Delivery resolution agent",
            slug=f"delivery-resolution-{uuid4().hex}",
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
            name="Delivery resolution connection",
            slug=f"delivery-resolution-{uuid4().hex}",
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            version=0,
            external_account_id=f"delivery-resolution-{uuid4().hex}",
            settings_json={},
            is_active=True,
        )
        principal = Principal(display_name="Delivery resolution principal")
        db.add_all([agent, connection, principal])
        await db.flush()
        route = ChannelAgentRoute(
            channel="whatsapp",
            route_key=f"delivery-resolution-{uuid4().hex}",
            channel_connection_id=connection.id,
            agent_id=agent.id,
            version=0,
            is_active=True,
        )
        db.add(route)
        await db.flush()
        conversation = ChatConversation(
            agent_id=agent.id,
            automation_agent_id=agent.id,
            automation_version=0,
            principal_id=principal.id,
            channel="whatsapp",
            external_thread_id=f"delivery-resolution-{uuid4().hex}",
            route_key=route.route_key,
            channel_route_id=route.id,
            status="active",
            control_mode="automated",
            control_version=0,
            transcript_consent=True,
            consent_version="test-v1",
        )
        db.add(conversation)
        await db.flush()
        unknown = _message(
            conversation=conversation,
            route=route,
            sequence=1,
            status="delivery_unknown",
            last_attempt_number=0,
            automation_agent_id=agent.id,
        )
        queued = _message(
            conversation=conversation,
            route=route,
            sequence=2,
            status="queued",
            last_attempt_number=0,
            automation_agent_id=agent.id,
        )
        db.add_all([unknown, queued])
        await db.flush()
        await db.commit()
        return _ResolutionGraph(
            agent_id=agent.id,
            admin_id=admin.id,
            connection_id=connection.id,
            route_id=route.id,
            principal_id=principal.id,
            conversation_id=conversation.id,
            unknown_id=unknown.id,
            queued_id=queued.id,
        )


def _message(
    *,
    conversation: ChatConversation,
    route: ChannelAgentRoute,
    sequence: int,
    status: str,
    last_attempt_number: int,
    automation_agent_id: UUID,
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
        payload_json={"text": "Sensitive content excluded from resolution"},
        destination="sensitive-destination",
        sender_type="automation",
        sender_admin_id=None,
        control_version=0,
        automation_agent_id=automation_agent_id,
        automation_version=0,
        sequence=sequence,
        idempotency_key=f"delivery-resolution-{uuid4().hex}",
        payload_hash="a" * 64,
        correlation_id=f"delivery-resolution-{uuid4().hex}",
        status=status,
        last_attempt_number=last_attempt_number,
        resolution_version=0,
    )


async def _cleanup_graph(graph: _ResolutionGraph) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Principal).where(Principal.id == graph.principal_id))
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id == graph.route_id)
        )
        await db.execute(
            delete(ChannelConnection).where(ChannelConnection.id == graph.connection_id)
        )
        await db.execute(delete(AgentProfile).where(AgentProfile.id == graph.agent_id))
        await db.commit()
