"""PostgreSQL coverage for conversation retention with commercial work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity
from app.models.platform import ChatConversation, Principal
from app.services.commercial.follow_up_read_models import (
    FollowUpReadNotFoundError,
    follow_up_read_service,
)
from app.services.retention import purge_expired_conversations

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class RetentionContext:
    agent_id: UUID
    principal_ids: tuple[UUID, UUID]
    conversation_ids: tuple[UUID, UUID]
    contact_ids: tuple[UUID, UUID]
    point_ids: tuple[UUID, UUID]
    consent_ids: tuple[UUID, UUID]
    opportunity_ids: tuple[UUID, UUID]
    task_ids: tuple[UUID, UUID]


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def retention_context() -> RetentionContext:
    context = RetentionContext(
        agent_id=uuid4(),
        principal_ids=(uuid4(), uuid4()),
        conversation_ids=(uuid4(), uuid4()),
        contact_ids=(uuid4(), uuid4()),
        point_ids=(uuid4(), uuid4()),
        consent_ids=(uuid4(), uuid4()),
        opportunity_ids=(uuid4(), uuid4()),
        task_ids=(uuid4(), uuid4()),
    )
    now = datetime.now(UTC)
    old = now - timedelta(days=60)
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=context.agent_id,
            name="Retention integration agent",
            slug=f"retention-integration-{suffix}",
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
        principals = [Principal(id=value) for value in context.principal_ids]
        db.add_all([agent, *principals])
        await db.flush()
        for index in range(2):
            conversation = ChatConversation(
                id=context.conversation_ids[index],
                agent_id=agent.id,
                automation_agent_id=agent.id,
                principal_id=context.principal_ids[index],
                channel="web",
                external_thread_id=f"retention-thread-{index}-{suffix}",
                route_key=f"retention-route-{index}-{suffix}",
                status="active",
                control_mode="automated",
            )
            contact = Contact(
                id=context.contact_ids[index],
                principal_id=context.principal_ids[index],
                created_by_agent_id=agent.id,
                status="active",
            )
            db.add_all([conversation, contact])
            await db.flush()
            point = ContactPoint(
                id=context.point_ids[index],
                contact_id=contact.id,
                kind="phone",
                ciphertext="gAAAAA" + ("x" * 80),
                lookup_hmac=(str(index + 1) * 64),
                masked_value="***0000",
                verification_status="verified",
                verified_at=now,
                source_conversation_id=conversation.id,
            )
            db.add(point)
            await db.flush()
            consent = ConsentRecord(
                id=context.consent_ids[index],
                principal_id=context.principal_ids[index],
                contact_id=contact.id,
                contact_point_id=point.id,
                agent_id=agent.id,
                purpose="commercial_follow_up",
                action="grant",
                policy_version="retention-v1",
                channel="web",
                target_channel="whatsapp",
                locale="en",
                source_conversation_id=conversation.id,
                correlation_id=f"retention-consent-{index}",
                idempotency_key=f"retention-consent-{index}-{suffix}",
                command_hash=str(index + 2) * 64,
                occurred_at=old,
            )
            opportunity = Opportunity(
                id=context.opportunity_ids[index],
                contact_id=contact.id,
                created_by_agent_id=agent.id,
                assigned_agent_id=agent.id,
                stage="qualified",
                control_version=0,
                title=f"Retention opportunity {index}",
                correlation_id=f"retention-opportunity-{index}",
                idempotency_key=f"retention-opportunity-{index}-{suffix}",
                command_hash=str(index + 4) * 64,
            )
            db.add_all([consent, opportunity])
            await db.flush()
            is_terminal = index == 0
            task = FollowUpTask(
                id=context.task_ids[index],
                opportunity_id=opportunity.id,
                conversation_id=conversation.id,
                source_conversation_id=conversation.id,
                fifo_key=f"conversation:{conversation.id}",
                target_channel="whatsapp",
                contact_point_id=point.id,
                consent_record_id=consent.id,
                executed_consent_record_id=consent.id if is_terminal else None,
                assigned_agent_id=agent.id,
                kind="commercial_follow_up",
                status="completed" if is_terminal else "scheduled",
                state_version=0,
                scheduled_control_version=0,
                scheduled_automation_version=0,
                scheduled_policy_version=0,
                due_at=old,
                available_at=old,
                attempts=1 if is_terminal else 0,
                max_attempts=3,
                had_chat_message_evidence=is_terminal,
                had_outbound_message_evidence=False,
                correlation_id=f"retention-task-{index}",
                idempotency_key=f"retention-task-{index}-{suffix}",
                command_hash=str(index + 6) * 64,
                completed_at=old if is_terminal else None,
            )
            db.add(task)
        await db.commit()
        await db.execute(
            update(ChatConversation)
            .where(ChatConversation.id.in_(context.conversation_ids))
            .values(updated_at=old)
        )
        await db.commit()

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.task_id.in_(context.task_ids)
                )
            )
            await db.execute(
                delete(FollowUpTask).where(FollowUpTask.id.in_(context.task_ids))
            )
            await db.execute(
                delete(Opportunity).where(Opportunity.id.in_(context.opportunity_ids))
            )
            await db.execute(
                delete(ConsentRecord).where(ConsentRecord.id.in_(context.consent_ids))
            )
            await db.execute(
                delete(ContactPoint).where(ContactPoint.id.in_(context.point_ids))
            )
            await db.execute(delete(Contact).where(Contact.id.in_(context.contact_ids)))
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id.in_(context.conversation_ids)
                )
            )
            await db.execute(
                delete(Principal).where(Principal.id.in_(context.principal_ids))
            )
            await db.execute(
                delete(AgentProfile).where(AgentProfile.id == context.agent_id)
            )
            await db.commit()


@pytest.mark.asyncio
async def test_retention_detaches_terminal_evidence_and_quarantines_active_work(
    retention_context: RetentionContext,
) -> None:
    context = retention_context
    async with AsyncSessionLocal() as db:
        deleted = await purge_expired_conversations(db, now=datetime.now(UTC))

    assert deleted == 1
    async with AsyncSessionLocal() as db:
        terminal = await db.get(FollowUpTask, context.task_ids[0])
        active = await db.get(FollowUpTask, context.task_ids[1])
        retained_conversation = await db.get(
            ChatConversation,
            context.conversation_ids[1],
        )
        event = (
            await db.execute(
                select(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.task_id == context.task_ids[1]
                )
            )
        ).scalar_one()

        assert terminal is not None
        assert terminal.conversation_id is None
        assert terminal.source_conversation_id == context.conversation_ids[0]
        assert terminal.had_chat_message_evidence is True
        assert active is not None
        assert active.status == "review_required"
        assert active.conversation_id == context.conversation_ids[1]
        assert retained_conversation is not None
        assert event.actor_type == "system"
        assert event.safe_code == "retention_conversation_blocked"


@pytest.mark.asyncio
async def test_follow_up_queue_isolated_by_current_opportunity_owner(
    retention_context: RetentionContext,
) -> None:
    context = retention_context
    async with AsyncSessionLocal() as db:
        page = await follow_up_read_service.list_tasks(
            db,
            agent_id=context.agent_id,
            status=None,
            kind=None,
            limit=100,
            offset=0,
        )
        foreign = await follow_up_read_service.list_tasks(
            db,
            agent_id=uuid4(),
            status=None,
            kind=None,
            limit=100,
            offset=0,
        )
        with pytest.raises(FollowUpReadNotFoundError):
            await follow_up_read_service.get_task(
                db,
                agent_id=uuid4(),
                task_id=context.task_ids[0],
            )

    assert page.total == 2
    assert foreign.total == 0
