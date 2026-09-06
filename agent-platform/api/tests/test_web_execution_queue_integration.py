"""PostgreSQL integration coverage for resumable web execution persistence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
)
from app.services.web_execution_queue import (
    WebExecutionIdempotencyConflictError,
    WebExecutionOutcome,
    WebExecutionQueueService,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _WebGraph:
    agent_id: UUID
    conversation_ids: tuple[UUID, UUID]
    principal_ids: tuple[UUID, UUID]


@pytest.fixture
async def web_graph():
    agent_id = None
    conversation_ids: tuple[UUID, UUID] = ()
    principal_ids: tuple[UUID, UUID] = ()
    try:
        async with AsyncSessionLocal() as db:
            profile = AgentProfile(
                name="Web queue integration agent",
                slug=f"web-queue-agent-{uuid4().hex}",
                version=1,
                is_active=True,
                is_public=True,
                retention_days=30,
                prompt_identity="test",
                prompt_domain="test",
                prompt_guardrails="test",
                unauthorized_message="unauthorized",
                error_message="error",
            )
            principals = [
                Principal(display_name="Web queue A"),
                Principal(display_name="Web queue B"),
            ]
            db.add_all([profile, *principals])
            await db.flush()
            conversations = [
                ChatConversation(
                    agent_id=profile.id,
                    principal_id=principal.id,
                    channel="web",
                    external_thread_id=f"web-session-{uuid4().hex}",
                    route_key=f"web-route-{uuid4().hex}",
                    transcript_consent=True,
                    consent_version="test-v1",
                )
                for principal in principals
            ]
            db.add_all(conversations)
            await db.commit()
            agent_id = profile.id
            conversation_ids = (conversations[0].id, conversations[1].id)
            principal_ids = (principals[0].id, principals[1].id)
            yield _WebGraph(
                agent_id=profile.id,
                conversation_ids=conversation_ids,
                principal_ids=principal_ids,
            )
    finally:
        async with AsyncSessionLocal() as db:
            if conversation_ids:
                await db.execute(
                    delete(ChatConversation).where(
                        ChatConversation.id.in_(conversation_ids)
                    )
                )
            if principal_ids:
                await db.execute(
                    delete(Principal).where(Principal.id.in_(principal_ids))
                )
            if agent_id is not None:
                await db.execute(
                    delete(AgentProfile).where(AgentProfile.id == agent_id)
                )
            await db.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_event_sequences_are_monotonic_under_concurrent_publish(web_graph):
    service = ConversationEventService()
    conversation_id = web_graph.conversation_ids[0]
    first_db = AsyncSessionLocal()
    second_db = AsyncSessionLocal()

    async def publish_second():
        event = await service.publish(
            second_db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            event_type="chat.execution.changed",
            visibility=ConversationEventVisibility.INTERNAL,
            payload={"status": "second"},
        )
        await second_db.commit()
        return event.sequence

    try:
        first = await service.publish(
            first_db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            event_type="chat.execution.changed",
            visibility=ConversationEventVisibility.INTERNAL,
            payload={"status": "first"},
        )
        competing = asyncio.create_task(publish_second())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(competing), timeout=0.05)
        await first_db.commit()
        second_sequence = await asyncio.wait_for(competing, timeout=2)

        assert first.sequence == 1
        assert second_sequence == 2
        async with AsyncSessionLocal() as reader:
            events = await service.list_after(
                reader,
                conversation_id=conversation_id,
                agent_id=web_graph.agent_id,
                after_sequence=0,
            )
            assert [event.sequence for event in events] == [1, 2]
    finally:
        await first_db.close()
        await second_db.close()


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_and_rejects_changed_input(web_graph):
    service = WebExecutionQueueService()
    conversation_id = web_graph.conversation_ids[0]

    async with AsyncSessionLocal() as db:
        first = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="client-message-1",
            content="I need a website",
            locale="es-AR",
        )
        duplicate = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="client-message-1",
            content="I need a website",
            locale="es-AR",
        )
        assert first.duplicate is False
        assert duplicate.duplicate is True
        assert duplicate.execution.id == first.execution.id
        assert first.execution.queue_sequence == first.accepted_event.sequence
        assert first.execution.automation_agent_id == web_graph.agent_id
        assert first.execution.automation_version == 0
        assert duplicate.accepted_event.id == first.accepted_event.id

        with pytest.raises(WebExecutionIdempotencyConflictError):
            await service.enqueue(
                db,
                conversation_id=conversation_id,
                agent_id=web_graph.agent_id,
                client_message_id="client-message-1",
                content="Changed request",
                locale="es-AR",
            )
        await db.commit()


@pytest.mark.asyncio
async def test_concurrent_duplicate_enqueue_returns_one_execution(web_graph):
    service = WebExecutionQueueService()
    conversation_id = web_graph.conversation_ids[0]
    first_db = AsyncSessionLocal()
    second_db = AsyncSessionLocal()

    async def enqueue_second():
        result = await service.enqueue(
            second_db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="concurrent-client-message",
            content="Same request",
            locale="es-AR",
        )
        await second_db.commit()
        return result

    try:
        first = await service.enqueue(
            first_db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="concurrent-client-message",
            content="Same request",
            locale="es-AR",
        )
        competing = asyncio.create_task(enqueue_second())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(competing), timeout=0.05)
        await first_db.commit()
        duplicate = await asyncio.wait_for(competing, timeout=2)

        assert first.duplicate is False
        assert duplicate.duplicate is True
        assert duplicate.execution.id == first.execution.id
        async with AsyncSessionLocal() as reader:
            executions = (
                (
                    await reader.execute(
                        select(ChatExecution).where(
                            ChatExecution.conversation_id == conversation_id,
                            ChatExecution.client_message_id
                            == "concurrent-client-message",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(executions) == 1
    finally:
        await first_db.close()
        await second_db.close()


@pytest.mark.asyncio
async def test_parallel_claims_use_distinct_conversations_and_fence_takeover(web_graph):
    service = WebExecutionQueueService()
    first_conversation, second_conversation = web_graph.conversation_ids

    async with AsyncSessionLocal() as db:
        first = await service.enqueue(
            db,
            conversation_id=first_conversation,
            agent_id=web_graph.agent_id,
            client_message_id="claim-first",
            content="First",
            locale="es-AR",
        )
        second = await service.enqueue(
            db,
            conversation_id=second_conversation,
            agent_id=web_graph.agent_id,
            client_message_id="claim-second",
            content="Second",
            locale="es-AR",
        )
        await db.commit()

    first_worker = AsyncSessionLocal()
    second_worker = AsyncSessionLocal()
    try:
        first_claim = await service.claim_next(
            first_worker,
            worker_id="web-worker-a",
            lease_duration=timedelta(minutes=5),
        )
        second_claim = await service.claim_next(
            second_worker,
            worker_id="web-worker-b",
            lease_duration=timedelta(minutes=5),
        )
        assert first_claim is not None
        assert second_claim is not None
        assert (
            first_claim.execution.conversation_id
            != second_claim.execution.conversation_id
        )
        await first_worker.commit()
        await second_worker.commit()
    finally:
        await first_worker.close()
        await second_worker.close()

    async with AsyncSessionLocal() as db:
        for execution_id in (first.execution.id, second.execution.id):
            execution = await db.get(ChatExecution, execution_id)
            assert execution is not None
            execution.status = "completed"
            execution.lease_owner = None
            execution.lease_expires_at = None
        first_conversation_model = await db.get(ChatConversation, first_conversation)
        assert first_conversation_model is not None
        first_conversation_model.control_mode = "paused"
        first_conversation_model.control_version += 1
        await db.commit()

        # Running work is guarded by the runtime; a newly queued stale epoch is
        # cancelled before it can begin.
        third = await service.enqueue(
            db,
            conversation_id=second_conversation,
            agent_id=web_graph.agent_id,
            client_message_id="takeover-fence",
            content="Fence me",
            locale="es-AR",
        )
        await db.commit()
        second_conversation_model = await db.get(ChatConversation, second_conversation)
        assert second_conversation_model is not None
        second_conversation_model.control_mode = "paused"
        second_conversation_model.control_version += 1
        await db.commit()

        claim = await service.claim_next(
            db,
            worker_id="web-worker-c",
            lease_duration=timedelta(minutes=5),
        )
        assert claim is None
        await db.refresh(third.execution)
        assert third.execution.status == "cancelled"
        assert third.execution.error_code == "conversation_control_changed"


@pytest.mark.asyncio
async def test_stale_lease_is_blocked_without_automatic_retry(web_graph):
    service = WebExecutionQueueService()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        queued = await service.enqueue(
            db,
            conversation_id=web_graph.conversation_ids[0],
            agent_id=web_graph.agent_id,
            client_message_id="stale-lease",
            content="Run once",
            locale="es-AR",
            available_at=now,
        )
        await db.commit()
        claimed = await service.claim_next(
            db,
            worker_id="stale-worker",
            lease_duration=timedelta(seconds=1),
            now=now,
        )
        assert claimed is not None
        await db.commit()

    async with AsyncSessionLocal() as db:
        recovered = await service.recover_stale_leases(
            db,
            now=now + timedelta(seconds=2),
        )
        assert recovered == 1
        execution = await db.get(ChatExecution, queued.execution.id)
        assert execution is not None
        assert execution.status == "blocked"
        assert execution.error_code == "stale_execution_lease"
        assert execution.attempt_count == 1
        assert execution.lease_owner is None
        assert execution.lease_expires_at is None
        event = (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id
                        == web_graph.conversation_ids[0],
                        ConversationEvent.event_type == "chat.execution.changed",
                        ConversationEvent.payload_json["status"].astext == "blocked",
                    )
                )
            )
            .scalars()
            .one()
        )
        assert event.visibility == "public"


@pytest.mark.asyncio
async def test_claim_cancels_a_stale_automation_epoch(web_graph):
    service = WebExecutionQueueService()
    conversation_id = web_graph.conversation_ids[0]

    async with AsyncSessionLocal() as db:
        queued = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="stale-automation-claim",
            content="Do not run with an obsolete specialist",
            locale="es-AR",
        )
        await db.commit()
        conversation = await db.get(ChatConversation, conversation_id)
        assert conversation is not None
        conversation.automation_version += 1
        await db.commit()

        claim = await service.claim_next(
            db,
            worker_id="automation-fence-worker",
            lease_duration=timedelta(minutes=5),
        )
        assert claim is None
        await db.refresh(queued.execution)
        assert queued.execution.status == "cancelled"
        assert queued.execution.error_code == "conversation_automation_changed"


@pytest.mark.asyncio
async def test_record_outcome_discards_a_stale_automation_result(web_graph):
    service = WebExecutionQueueService()
    conversation_id = web_graph.conversation_ids[0]

    async with AsyncSessionLocal() as db:
        queued = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="stale-automation-outcome",
            content="Do not publish with an obsolete specialist",
            locale="es-AR",
        )
        await db.commit()
        claim = await service.claim_next(
            db,
            worker_id="automation-outcome-worker",
            lease_duration=timedelta(minutes=5),
        )
        assert claim is not None
        await db.commit()

    async with AsyncSessionLocal() as assignment_db:
        conversation = await assignment_db.get(ChatConversation, conversation_id)
        assert conversation is not None
        conversation.automation_version += 1
        await assignment_db.commit()

    async with AsyncSessionLocal() as db:
        blocked = await service.record_outcome(
            db,
            execution_id=queued.execution.id,
            worker_id="automation-outcome-worker",
            outcome=WebExecutionOutcome.COMPLETED,
            output_content="Stale automatic answer",
        )
        await db.commit()
        assert blocked.published is False
        assert blocked.execution.status == "blocked"
        assert blocked.execution.error_code == "conversation_automation_changed"
        output = (
            await db.execute(
                select(ChatMessage.id).where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.content == "Stale automatic answer",
                )
            )
        ).scalar_one_or_none()
        assert output is None


@pytest.mark.asyncio
async def test_completion_is_atomic_and_takeover_discards_late_output(web_graph):
    service = WebExecutionQueueService()
    conversation_id = web_graph.conversation_ids[0]

    async with AsyncSessionLocal() as db:
        first = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="completed-message",
            content="Complete this",
            locale="es-AR",
        )
        await db.commit()
        claimed = await service.claim_next(
            db,
            worker_id="completion-worker",
            lease_duration=timedelta(minutes=5),
        )
        assert claimed is not None
        await db.commit()
        completed = await service.record_outcome(
            db,
            execution_id=first.execution.id,
            worker_id="completion-worker",
            outcome=WebExecutionOutcome.COMPLETED,
            output_content="Completed answer",
            tools_used=["catalog.lookup"],
            usage={"input_tokens": 10},
            duration_ms=25,
        )
        await db.commit()

        assert completed.published is True
        assert completed.execution.status == "completed"
        output = await db.get(ChatMessage, completed.execution.output_message_id)
        assert output is not None
        assert output.content == "Completed answer"
        completion_event = (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == conversation_id,
                        ConversationEvent.event_type == "chat.message.completed",
                    )
                )
            )
            .scalars()
            .one()
        )
        assert completion_event.payload_json["content"] == "Completed answer"

        late = await service.enqueue(
            db,
            conversation_id=conversation_id,
            agent_id=web_graph.agent_id,
            client_message_id="late-message",
            content="Do not publish this",
            locale="es-AR",
        )
        await db.commit()
        late_claim = await service.claim_next(
            db,
            worker_id="late-worker",
            lease_duration=timedelta(minutes=5),
        )
        assert late_claim is not None
        await db.commit()

    async with AsyncSessionLocal() as control_db:
        conversation = await control_db.get(ChatConversation, conversation_id)
        assert conversation is not None
        conversation.control_mode = "paused"
        conversation.control_version += 1
        await control_db.commit()

    async with AsyncSessionLocal() as db:
        blocked = await service.record_outcome(
            db,
            execution_id=late.execution.id,
            worker_id="late-worker",
            outcome=WebExecutionOutcome.COMPLETED,
            output_content="Late automatic answer",
        )
        await db.commit()

        assert blocked.published is False
        assert blocked.execution.status == "blocked"
        late_output = (
            await db.execute(
                select(ChatMessage.id).where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.client_message_id == "late-message:assistant",
                )
            )
        ).scalar_one_or_none()
        assert late_output is None
