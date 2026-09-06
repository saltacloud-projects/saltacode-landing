"""PostgreSQL coverage for consent-fenced commercial outbound dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.follow_up import FollowUpTask
from app.models.opportunity import Opportunity
from app.models.outbound import OutboundMessage
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.ports.outbound import Accepted
from app.services.commercial.consents import (
    ConsentAction,
    ConsentPurpose,
    ConsentService,
)
from app.services.outbound_delivery import (
    OutboundDeliveryService,
    OutboundKind,
    OutboundSenderType,
)
from app.services.outbound_dispatcher import OutboundDispatcher
from app.services.outbound_follow_up import FollowUpDispatchAuthorizationService

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _Context:
    agent_id: UUID
    connection_id: UUID
    route_id: UUID
    principal_id: UUID
    identity_id: UUID
    conversation_id: UUID
    contact_id: UUID
    point_id: UUID
    consent_id: UUID
    opportunity_id: UUID
    task_id: UUID
    outbound_id: UUID


class _BlockingAdapter:
    adapter_key = "meta_whatsapp_cloud"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def deliver(self, *, message, route, connection):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return Accepted("wamid.follow-up")


class _RecordingAdapter:
    adapter_key = "meta_whatsapp_cloud"

    def __init__(self) -> None:
        self.calls = 0

    async def deliver(self, *, message, route, connection):
        self.calls += 1
        return Accepted("wamid.must-not-send")


class _FakeCrypto:
    def decrypt(self, _ciphertext: str) -> str:
        return "+5493870000000"


def _dispatcher(*, worker_id: str, adapter) -> OutboundDispatcher:
    return OutboundDispatcher(
        worker_id=worker_id,
        stale_seconds=300,
        adapters=[adapter],
        follow_up_authorization=FollowUpDispatchAuthorizationService(
            crypto=_FakeCrypto()
        ),
    )


@pytest.fixture
async def follow_up_dispatch_context() -> _Context:
    context = await _create_context()
    try:
        yield context
    finally:
        await _cleanup(context)
        await engine.dispose()


@pytest.mark.asyncio
async def test_consent_revocation_waits_for_provider_result_commit(
    follow_up_dispatch_context,
):
    context = follow_up_dispatch_context
    adapter = _BlockingAdapter()
    dispatcher = _dispatcher(worker_id="follow-up-lock-worker", adapter=adapter)
    claim = await dispatcher.claim_once()
    assert claim is not None

    dispatch = asyncio.create_task(dispatcher.dispatch_claim(claim))
    await asyncio.wait_for(adapter.started.wait(), timeout=2)
    revoke = asyncio.create_task(_revoke(context))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(revoke), timeout=0.05)

    adapter.release.set()
    await asyncio.wait_for(dispatch, timeout=2)
    await asyncio.wait_for(revoke, timeout=2)

    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, context.outbound_id)
        task = await db.get(FollowUpTask, context.task_id)
        assert message is not None
        assert task is not None
        assert message.status == "accepted"
        assert message.provider_message_id == "wamid.follow-up"
        assert task.executed_consent_record_id == context.consent_id


@pytest.mark.asyncio
async def test_revoked_follow_up_is_cancelled_before_provider_io(
    follow_up_dispatch_context,
):
    context = follow_up_dispatch_context
    await _revoke(context)
    adapter = _RecordingAdapter()
    dispatcher = _dispatcher(worker_id="follow-up-revoked-worker", adapter=adapter)

    assert await dispatcher.run_once() is True

    assert adapter.calls == 0
    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, context.outbound_id)
        assert message is not None
        assert message.status == "cancelled"


@pytest.mark.asyncio
async def test_changed_follow_up_task_is_cancelled_before_provider_io(
    follow_up_dispatch_context,
):
    context = follow_up_dispatch_context
    adapter = _RecordingAdapter()
    dispatcher = _dispatcher(worker_id="follow-up-task-fence", adapter=adapter)
    claim = await dispatcher.claim_once()
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            task = await db.get(FollowUpTask, context.task_id)
            assert task is not None
            task.status = "review_required"
            task.review_required_at = datetime.now(UTC)
            task.state_version += 1

    await dispatcher.dispatch_claim(claim)

    assert adapter.calls == 0
    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, context.outbound_id)
        assert message is not None
        assert message.status == "cancelled"


async def _create_context() -> _Context:
    suffix = uuid4().hex
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            name="Follow-up outbound agent",
            slug=f"follow-up-outbound-{suffix}",
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
            name="Follow-up outbound connection",
            slug=f"follow-up-outbound-{suffix}",
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            version=0,
            external_account_id=f"follow-up-{suffix}",
            settings_json={},
            is_active=True,
        )
        principal = Principal(display_name="Follow-up outbound principal")
        db.add_all([agent, connection, principal])
        await db.flush()
        route = ChannelAgentRoute(
            channel="whatsapp",
            version=0,
            route_key=f"follow-up-outbound-{suffix}",
            channel_connection_id=connection.id,
            agent_id=agent.id,
            is_active=True,
        )
        identity = ChannelIdentity(
            principal_id=principal.id,
            channel="whatsapp",
            route_key=route.route_key,
            external_subject="5493870000000",
            verified=True,
        )
        db.add_all([route, identity])
        await db.flush()
        conversation = ChatConversation(
            agent_id=agent.id,
            automation_agent_id=agent.id,
            automation_version=0,
            principal_id=principal.id,
            channel="whatsapp",
            external_thread_id="5493870000000",
            route_key=route.route_key,
            channel_route_id=route.id,
            transcript_consent=True,
        )
        contact = Contact(
            principal_id=principal.id,
            created_by_agent_id=agent.id,
            status="active",
        )
        db.add_all([conversation, contact])
        await db.flush()
        point = ContactPoint(
            contact_id=contact.id,
            kind="phone",
            ciphertext="gAAAAA" + ("x" * 80),
            lookup_hmac="a" * 64,
            masked_value="+54*******0000",
            verification_status="verified",
            verified_at=now,
            source_conversation_id=conversation.id,
            source_channel_identity_id=identity.id,
        )
        opportunity = Opportunity(
            contact_id=contact.id,
            created_by_agent_id=agent.id,
            assigned_agent_id=agent.id,
            stage="qualified",
            control_version=0,
            title="Follow-up outbound opportunity",
            correlation_id=f"follow-up-{suffix}",
            idempotency_key=f"follow-up-{suffix}",
            command_hash="a" * 64,
        )
        db.add_all([point, opportunity])
        await db.flush()
        consent = ConsentRecord(
            principal_id=principal.id,
            contact_id=contact.id,
            contact_point_id=point.id,
            agent_id=agent.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.GRANT,
            policy_version="commercial-v1",
            channel="whatsapp",
            target_channel="whatsapp",
            locale="es-AR",
            source_conversation_id=conversation.id,
            source_channel_identity_id=identity.id,
            correlation_id=f"follow-up-consent-{suffix}",
            idempotency_key=f"follow-up-consent-{suffix}",
            command_hash="b" * 64,
            occurred_at=now,
        )
        db.add(consent)
        await db.flush()
        outbound = (
            await OutboundDeliveryService().enqueue(
                db,
                conversation_id=conversation.id,
                agent_id=agent.id,
                chat_message_id=None,
                kind=OutboundKind.TEXT,
                payload={"text": "Synthetic consent-fenced follow-up"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=0,
                automation_agent_id=agent.id,
                automation_version=0,
                idempotency_key=f"follow-up-outbound-{suffix}",
                correlation_id=f"follow-up-outbound-{suffix}",
            )
        ).message
        task = FollowUpTask(
            opportunity_id=opportunity.id,
            conversation_id=conversation.id,
            fifo_key=f"conversation:{conversation.id}",
            target_channel="whatsapp",
            contact_point_id=point.id,
            consent_record_id=consent.id,
            assigned_agent_id=agent.id,
            outbound_message_id=outbound.id,
            kind="commercial_follow_up",
            status="dispatch_queued",
            state_version=1,
            scheduled_control_version=0,
            scheduled_automation_version=0,
            scheduled_policy_version=0,
            due_at=now + timedelta(minutes=1),
            available_at=now,
            attempts=0,
            max_attempts=3,
            correlation_id=f"follow-up-task-{suffix}",
            idempotency_key=f"follow-up-task-{suffix}",
            command_hash="c" * 64,
        )
        db.add(task)
        await db.commit()
        return _Context(
            agent_id=agent.id,
            connection_id=connection.id,
            route_id=route.id,
            principal_id=principal.id,
            identity_id=identity.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            point_id=point.id,
            consent_id=consent.id,
            opportunity_id=opportunity.id,
            task_id=task.id,
            outbound_id=outbound.id,
        )


async def _revoke(context: _Context) -> None:
    async with AsyncSessionLocal() as db:
        await ConsentService().record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=context.contact_id,
            contact_point_id=context.point_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.REVOKE,
            policy_version="commercial-v1",
            channel="whatsapp",
            target_channel="whatsapp",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id=f"revoke-{uuid4().hex}",
            idempotency_key=f"revoke-{uuid4().hex}",
            occurred_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        await db.commit()


async def _cleanup(context: _Context) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(FollowUpTask).where(FollowUpTask.id == context.task_id))
        await db.execute(
            delete(OutboundMessage).where(OutboundMessage.id == context.outbound_id)
        )
        await db.execute(
            delete(ConsentRecord).where(ConsentRecord.contact_id == context.contact_id)
        )
        await db.execute(
            delete(Opportunity).where(Opportunity.id == context.opportunity_id)
        )
        await db.execute(delete(Contact).where(Contact.id == context.contact_id))
        await db.execute(
            delete(ChatConversation).where(
                ChatConversation.id == context.conversation_id
            )
        )
        await db.execute(
            delete(ChannelIdentity).where(ChannelIdentity.id == context.identity_id)
        )
        await db.execute(delete(Principal).where(Principal.id == context.principal_id))
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id == context.route_id)
        )
        await db.execute(
            delete(ChannelConnection).where(
                ChannelConnection.id == context.connection_id
            )
        )
        await db.execute(
            delete(AgentProfile).where(AgentProfile.id == context.agent_id)
        )
        await db.commit()
