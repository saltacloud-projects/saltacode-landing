"""PostgreSQL integration coverage for outbound queue ordering and fencing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryEvent,
    OutboundMessage,
)
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.ports.outbound import Accepted, Rejected, Unknown
from app.services.outbound_delivery import (
    DispatchOutcome,
    OutboundConversationNotFoundError,
    OutboundDeliveryService,
    OutboundFenceViolationError,
    OutboundIdempotencyConflictError,
    OutboundKind,
    OutboundSenderType,
)
from app.services.outbound_dispatcher import OutboundDispatcher
from app.workers.outbound import check_worker_health

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _OutboundGraph:
    agent_id: UUID
    admin_id: UUID
    conversation_ids: tuple[UUID, UUID]
    message_ids: tuple[UUID, ...]
    principal_ids: tuple[UUID, UUID]
    route_id: UUID
    connection_id: UUID


class _RecordingAdapter:
    channel = "whatsapp"

    def __init__(self, result):
        self.result = result
        self.calls = []
        self.claim_was_committed = False

    async def deliver(self, *, message, route, connection):
        async with AsyncSessionLocal() as observer:
            persisted = await observer.get(OutboundMessage, message.id)
            self.claim_was_committed = bool(
                persisted is not None
                and persisted.status == "dispatching"
                and persisted.locked_by is not None
            )
        self.calls.append((message.id, route.id, connection.id))
        return self.result


@pytest.fixture
async def outbound_graph():
    profile_id = None
    connection_id = None
    route_id = None
    principal_ids: tuple[UUID, UUID] = ()
    conversation_ids: tuple[UUID, UUID] = ()
    try:
        async with AsyncSessionLocal() as db:
            admin = (
                (
                    await db.execute(
                        select(AdminUser).where(AdminUser.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            assert admin is not None
            profile = AgentProfile(
                name="Outbound integration agent",
                slug=f"outbound-agent-{uuid4().hex}",
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
                name="Outbound integration connection",
                slug=f"outbound-connection-{uuid4().hex}",
                channel="whatsapp",
                external_account_id=f"outbound-account-{uuid4().hex}",
                settings_json={},
                is_active=True,
            )
            db.add_all([profile, connection])
            await db.flush()
            route = ChannelAgentRoute(
                channel="whatsapp",
                route_key=f"outbound-route-{uuid4().hex}",
                channel_connection_id=connection.id,
                agent_id=profile.id,
                is_active=True,
            )
            principals = [
                Principal(display_name="Outbound test A"),
                Principal(display_name="Outbound test B"),
            ]
            db.add_all([route, *principals])
            await db.flush()
            conversations = [
                ChatConversation(
                    agent_id=profile.id,
                    principal_id=principal.id,
                    channel="whatsapp",
                    external_thread_id=f"outbound-subject-{uuid4().hex}",
                    route_key=route.route_key,
                    channel_route_id=route.id,
                    transcript_consent=True,
                    consent_version="test-v1",
                )
                for principal in principals
            ]
            db.add_all(conversations)
            await db.flush()
            messages = [
                ChatMessage(
                    conversation_id=conversation.id,
                    client_message_id=f"outbound-chat-{uuid4().hex}",
                    role="assistant",
                    content=f"Synthetic outbound {index}",
                    status="pending_delivery",
                )
                for index, conversation in enumerate(
                    [
                        conversations[0],
                        conversations[0],
                        conversations[0],
                        conversations[1],
                    ],
                    start=1,
                )
            ]
            db.add_all(messages)
            await db.commit()

            profile_id = profile.id
            connection_id = connection.id
            route_id = route.id
            principal_ids = (principals[0].id, principals[1].id)
            conversation_ids = (conversations[0].id, conversations[1].id)
            yield _OutboundGraph(
                agent_id=profile.id,
                admin_id=admin.id,
                conversation_ids=conversation_ids,
                message_ids=tuple(message.id for message in messages),
                principal_ids=principal_ids,
                route_id=route.id,
                connection_id=connection.id,
            )
    finally:
        async with AsyncSessionLocal() as db:
            if conversation_ids:
                await db.execute(
                    delete(OutboundMessage).where(
                        OutboundMessage.conversation_id.in_(conversation_ids)
                    )
                )
            if principal_ids:
                await db.execute(
                    delete(Principal).where(Principal.id.in_(principal_ids))
                )
            if route_id is not None:
                await db.execute(
                    delete(ChannelAgentRoute).where(ChannelAgentRoute.id == route_id)
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
        await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_agent_scoped_and_control_fenced(outbound_graph):
    service = OutboundDeliveryService()
    conversation_id = outbound_graph.conversation_ids[0]
    first_message_id, second_message_id = outbound_graph.message_ids[:2]

    async with AsyncSessionLocal() as db:
        first = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=outbound_graph.agent_id,
            chat_message_id=first_message_id,
            kind=OutboundKind.TEXT,
            payload={"text": "First automated answer"},
            sender_type=OutboundSenderType.AUTOMATION,
            control_version=0,
            automation_agent_id=outbound_graph.agent_id,
            automation_version=0,
            idempotency_key="automatic-answer-1",
            correlation_id="request-1",
        )
        duplicate = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=outbound_graph.agent_id,
            chat_message_id=first_message_id,
            kind=OutboundKind.TEXT,
            payload={"text": "First automated answer"},
            sender_type=OutboundSenderType.AUTOMATION,
            control_version=0,
            automation_agent_id=outbound_graph.agent_id,
            automation_version=0,
            idempotency_key="automatic-answer-1",
            correlation_id="request-1-retry",
        )
        assert first.duplicate is False
        assert duplicate.duplicate is True
        assert duplicate.message.id == first.message.id
        assert duplicate.message.correlation_id == "request-1"

        with pytest.raises(OutboundIdempotencyConflictError):
            await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=outbound_graph.agent_id,
                chat_message_id=first_message_id,
                kind=OutboundKind.TEXT,
                payload={"text": "Changed automated answer"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=0,
                automation_agent_id=outbound_graph.agent_id,
                automation_version=0,
                idempotency_key="automatic-answer-1",
                correlation_id="request-1",
            )
        with pytest.raises(OutboundIdempotencyConflictError):
            await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=outbound_graph.agent_id,
                chat_message_id=first_message_id,
                kind=OutboundKind.TEMPLATE,
                payload={"template_key": "follow_up", "language": "es_AR"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=0,
                automation_agent_id=outbound_graph.agent_id,
                automation_version=0,
                idempotency_key="automatic-answer-1",
                correlation_id="request-kind-conflict",
            )
        with pytest.raises(OutboundConversationNotFoundError):
            await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=uuid4(),
                chat_message_id=second_message_id,
                kind=OutboundKind.TEXT,
                payload={"text": "Cross-agent answer"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=0,
                automation_agent_id=outbound_graph.agent_id,
                automation_version=0,
                idempotency_key="cross-agent",
                correlation_id="request-cross-agent",
            )

        conversation = await db.get(ChatConversation, conversation_id)
        assert conversation is not None
        conversation.control_mode = "human"
        conversation.control_version = 1
        conversation.assigned_admin_id = outbound_graph.admin_id
        with pytest.raises(OutboundFenceViolationError):
            await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=outbound_graph.agent_id,
                chat_message_id=second_message_id,
                kind=OutboundKind.TEXT,
                payload={"text": "Blocked automated answer"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=1,
                automation_agent_id=outbound_graph.agent_id,
                automation_version=0,
                idempotency_key="blocked-automation",
                correlation_id="request-2",
            )
        with pytest.raises(OutboundIdempotencyConflictError):
            await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=outbound_graph.agent_id,
                chat_message_id=first_message_id,
                kind=OutboundKind.TEXT,
                payload={"text": "First automated answer"},
                sender_type=OutboundSenderType.OPERATOR,
                sender_admin_id=outbound_graph.admin_id,
                control_version=1,
                idempotency_key="automatic-answer-1",
                correlation_id="request-owner-conflict",
            )
        operator = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=outbound_graph.agent_id,
            chat_message_id=second_message_id,
            kind=OutboundKind.TEXT,
            payload={"text": "Operator answer"},
            sender_type=OutboundSenderType.OPERATOR,
            sender_admin_id=outbound_graph.admin_id,
            control_version=1,
            idempotency_key="operator-answer-1",
            correlation_id="request-2",
        )
        await db.commit()

        assert operator.message.sequence == 2
        assert operator.message.automation_agent_id is None
        assert operator.message.automation_version is None
        assert conversation.next_outbound_sequence == 3
        event_count = (
            await db.execute(
                select(func.count(OutboundDeliveryEvent.id)).where(
                    OutboundDeliveryEvent.outbound_message_id.in_(
                        [first.message.id, operator.message.id]
                    )
                )
            )
        ).scalar_one()
        assert event_count == 2

        claimed = await service.claim_next(
            db,
            worker_id="operator-delivery-worker",
            stale_before=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        assert claimed is not None
        assert claimed.message.id == operator.message.id
        cancelled = await db.get(OutboundMessage, first.message.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        await db.commit()


@pytest.mark.asyncio
async def test_concurrent_duplicate_enqueue_returns_the_same_record(outbound_graph):
    service = OutboundDeliveryService()
    conversation_id = outbound_graph.conversation_ids[0]
    chat_message_id = outbound_graph.message_ids[0]
    first_db = AsyncSessionLocal()
    second_db = AsyncSessionLocal()

    async def enqueue_second():
        result = await service.enqueue(
            second_db,
            conversation_id=conversation_id,
            agent_id=outbound_graph.agent_id,
            chat_message_id=chat_message_id,
            kind=OutboundKind.TEXT,
            payload={"text": "Concurrent answer"},
            sender_type=OutboundSenderType.AUTOMATION,
            control_version=0,
            automation_agent_id=outbound_graph.agent_id,
            automation_version=0,
            idempotency_key="concurrent-idempotency",
            correlation_id="concurrent-request",
        )
        await second_db.commit()
        return result

    try:
        first = await service.enqueue(
            first_db,
            conversation_id=conversation_id,
            agent_id=outbound_graph.agent_id,
            chat_message_id=chat_message_id,
            kind=OutboundKind.TEXT,
            payload={"text": "Concurrent answer"},
            sender_type=OutboundSenderType.AUTOMATION,
            control_version=0,
            automation_agent_id=outbound_graph.agent_id,
            automation_version=0,
            idempotency_key="concurrent-idempotency",
            correlation_id="concurrent-request",
        )
        competing = asyncio.create_task(enqueue_second())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(competing), timeout=0.05)

        await first_db.commit()
        duplicate = await asyncio.wait_for(competing, timeout=2)
        assert duplicate.duplicate is True
        assert duplicate.message.id == first.message.id
    finally:
        await first_db.close()
        await second_db.close()


@pytest.mark.asyncio
async def test_frozen_file_command_survives_chat_message_change_and_delete(
    outbound_graph,
):
    service = OutboundDeliveryService()
    payload = {
        "storage_key": "blobs/ab/proposal.pdf",
        "name": "proposal.pdf",
        "mime": "application/pdf",
        "caption": "Requested proposal",
    }

    async with AsyncSessionLocal() as db:
        result = await service.enqueue(
            db,
            conversation_id=outbound_graph.conversation_ids[0],
            agent_id=outbound_graph.agent_id,
            chat_message_id=outbound_graph.message_ids[0],
            kind=OutboundKind.DOCUMENT,
            payload=payload,
            sender_type=OutboundSenderType.AUTOMATION,
            control_version=0,
            automation_agent_id=outbound_graph.agent_id,
            automation_version=0,
            idempotency_key="frozen-document",
            correlation_id="frozen-document-request",
        )
        await db.commit()

        chat_message = await db.get(ChatMessage, outbound_graph.message_ids[0])
        assert chat_message is not None
        chat_message.content = "mutated source message"
        await db.flush()
        await db.refresh(result.message)
        assert result.message.payload_json == payload

        await db.delete(chat_message)
        await db.commit()
        await db.refresh(result.message)
        assert result.message.chat_message_id is None
        assert result.message.kind == "document"
        assert result.message.payload_json == payload

        result.message.status = "delivered"
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_claim_is_fifo_parallel_and_stale_dispatch_blocks_only_its_conversation(
    outbound_graph,
):
    service = OutboundDeliveryService()
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=30)
    first_conversation, second_conversation = outbound_graph.conversation_ids
    first_message, second_message, third_message, other_message = (
        outbound_graph.message_ids
    )

    async with AsyncSessionLocal() as db:
        queued = []
        for offset, (conversation_id, chat_message_id) in enumerate(
            [
                (first_conversation, first_message),
                (first_conversation, second_message),
                (first_conversation, third_message),
                (second_conversation, other_message),
            ]
        ):
            result = await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=outbound_graph.agent_id,
                chat_message_id=chat_message_id,
                kind=OutboundKind.TEXT,
                payload={"text": f"FIFO answer {offset}"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=0,
                automation_agent_id=outbound_graph.agent_id,
                automation_version=0,
                idempotency_key=f"fifo-{offset}",
                correlation_id=f"fifo-request-{offset}",
            )
            result.message.created_at = now + timedelta(seconds=offset)
            queued.append(result.message)
        await db.commit()

    first_worker = AsyncSessionLocal()
    second_worker = AsyncSessionLocal()
    try:
        first_claim = await service.claim_next(
            first_worker,
            worker_id="worker-a",
            stale_before=stale_before,
            now=now,
        )
        assert first_claim is not None
        assert first_claim.message.id == queued[0].id

        second_claim = await service.claim_next(
            second_worker,
            worker_id="worker-b",
            stale_before=stale_before,
            now=now,
        )
        assert second_claim is not None
        assert second_claim.message.id == queued[3].id
        assert (
            second_claim.message.conversation_id != first_claim.message.conversation_id
        )

        await service.record_dispatch_outcome(
            first_worker,
            outbound_message_id=first_claim.message.id,
            attempt_id=first_claim.attempt.id,
            worker_id="worker-a",
            outcome=DispatchOutcome.ACCEPTED,
            provider_message_id="provider-a",
        )
        await first_worker.commit()
        await service.record_dispatch_outcome(
            second_worker,
            outbound_message_id=second_claim.message.id,
            attempt_id=second_claim.attempt.id,
            worker_id="worker-b",
            outcome=DispatchOutcome.ACCEPTED,
            provider_message_id="provider-b",
        )
        await second_worker.commit()
    finally:
        await first_worker.close()
        await second_worker.close()

    async with AsyncSessionLocal() as db:
        stale_claim = await service.claim_next(
            db,
            worker_id="worker-c",
            stale_before=stale_before,
            now=now,
        )
        assert stale_claim is not None
        assert stale_claim.message.id == queued[1].id
        stale_claim.message.locked_at = now - timedelta(hours=2)
        await db.commit()

    async with AsyncSessionLocal() as db:
        blocked = await service.claim_next(
            db,
            worker_id="worker-d",
            stale_before=stale_before,
            now=now,
        )
        assert blocked is None
        uncertain = await db.get(OutboundMessage, queued[1].id)
        still_queued = await db.get(OutboundMessage, queued[2].id)
        assert uncertain is not None
        assert uncertain.status == "delivery_unknown"
        assert still_queued is not None
        assert still_queued.status == "queued"

        attempts = (
            (
                await db.execute(
                    select(OutboundAttempt).where(
                        OutboundAttempt.outbound_message_id == queued[1].id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(attempts) == 1
        assert "updated_at" not in OutboundAttempt.__table__.columns
        recovery_event = (
            (
                await db.execute(
                    select(OutboundDeliveryEvent).where(
                        OutboundDeliveryEvent.outbound_message_id == queued[1].id,
                        OutboundDeliveryEvent.event_type == "delivery_unknown",
                    )
                )
            )
            .scalars()
            .one()
        )
        assert recovery_event.safe_code == "stale_dispatch"


async def _enqueue_dispatcher_text(
    graph: _OutboundGraph,
    *,
    message_index: int,
    idempotency_key: str,
) -> UUID:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await OutboundDeliveryService().enqueue(
                db,
                conversation_id=graph.conversation_ids[0],
                agent_id=graph.agent_id,
                chat_message_id=graph.message_ids[message_index],
                kind=OutboundKind.TEXT,
                payload={"text": f"Dispatcher answer {message_index}"},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=0,
                automation_agent_id=graph.agent_id,
                automation_version=0,
                idempotency_key=idempotency_key,
                correlation_id=f"correlation-{idempotency_key}",
            )
            return result.message.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_result", "expected_status", "expected_provider_id"),
    [
        (Accepted("wamid.accepted"), "accepted", "wamid.accepted"),
        (Rejected("provider_http_400"), "failed", None),
        (Unknown("provider_timeout"), "delivery_unknown", None),
    ],
)
async def test_dispatcher_commits_claim_before_io_and_persists_typed_outcome(
    outbound_graph,
    adapter_result,
    expected_status,
    expected_provider_id,
):
    outbound_id = await _enqueue_dispatcher_text(
        outbound_graph,
        message_index=0,
        idempotency_key=f"typed-{expected_status}",
    )
    adapter = _RecordingAdapter(adapter_result)
    dispatcher = OutboundDispatcher(
        worker_id=f"worker-{expected_status}",
        stale_seconds=300,
        adapters=[adapter],
    )

    assert await dispatcher.run_once() is True
    assert adapter.claim_was_committed is True
    assert len(adapter.calls) == 1
    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, outbound_id)
        assert message is not None
        assert message.status == expected_status
        assert message.provider_message_id == expected_provider_id
        assert message.locked_by is None


@pytest.mark.asyncio
async def test_dispatcher_revalidates_control_before_provider_call(outbound_graph):
    outbound_id = await _enqueue_dispatcher_text(
        outbound_graph,
        message_index=0,
        idempotency_key="fence-before-send",
    )
    adapter = _RecordingAdapter(Accepted("must-not-send"))
    dispatcher = OutboundDispatcher(
        worker_id="worker-fence",
        stale_seconds=300,
        adapters=[adapter],
    )
    claim = await dispatcher.claim_once()
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            conversation = await db.get(
                ChatConversation,
                outbound_graph.conversation_ids[0],
            )
            assert conversation is not None
            conversation.control_mode = "human"
            conversation.control_version = 1
            conversation.assigned_admin_id = outbound_graph.admin_id

    await dispatcher.dispatch_claim(claim)

    assert adapter.calls == []
    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, outbound_id)
        assert message is not None
        assert message.status == "cancelled"


@pytest.mark.asyncio
async def test_dispatcher_revalidates_automation_before_provider_call(outbound_graph):
    outbound_id = await _enqueue_dispatcher_text(
        outbound_graph,
        message_index=0,
        idempotency_key="automation-fence-before-send",
    )
    adapter = _RecordingAdapter(Accepted("must-not-send"))
    dispatcher = OutboundDispatcher(
        worker_id="worker-automation-fence",
        stale_seconds=300,
        adapters=[adapter],
    )
    claim = await dispatcher.claim_once()
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            conversation = await db.get(
                ChatConversation,
                outbound_graph.conversation_ids[0],
            )
            assert conversation is not None
            conversation.automation_version = 1

    await dispatcher.dispatch_claim(claim)

    assert adapter.calls == []
    async with AsyncSessionLocal() as db:
        message = await db.get(OutboundMessage, outbound_id)
        assert message is not None
        assert message.status == "cancelled"
        event = (
            (
                await db.execute(
                    select(OutboundDeliveryEvent)
                    .where(
                        OutboundDeliveryEvent.outbound_message_id == outbound_id,
                        OutboundDeliveryEvent.event_type == "cancelled",
                    )
                    .order_by(OutboundDeliveryEvent.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert event is not None
        assert event.safe_code == "conversation_automation_changed"


@pytest.mark.asyncio
async def test_delivery_unknown_blocks_fifo_without_retry(outbound_graph):
    first_id = await _enqueue_dispatcher_text(
        outbound_graph,
        message_index=0,
        idempotency_key="unknown-head",
    )
    second_id = await _enqueue_dispatcher_text(
        outbound_graph,
        message_index=1,
        idempotency_key="blocked-tail",
    )
    adapter = _RecordingAdapter(Unknown("provider_timeout"))
    dispatcher = OutboundDispatcher(
        worker_id="worker-unknown",
        stale_seconds=300,
        adapters=[adapter],
    )

    assert await dispatcher.run_once() is True
    assert await dispatcher.run_once() is False
    assert len(adapter.calls) == 1
    async with AsyncSessionLocal() as db:
        first = await db.get(OutboundMessage, first_id)
        second = await db.get(OutboundMessage, second_id)
        assert first is not None
        assert second is not None
        assert first.status == "delivery_unknown"
        assert second.status == "queued"


@pytest.mark.asyncio
async def test_outbound_worker_healthchecks_schema_and_storage(monkeypatch, tmp_path):
    from app.workers import outbound as module

    monkeypatch.setattr(module.settings, "document_storage_root", str(tmp_path))

    await check_worker_health()
