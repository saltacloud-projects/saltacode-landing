"""PostgreSQL integration coverage for auditable meeting coordination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.contact import Contact
from app.models.meeting import Meeting, MeetingEvent, MeetingSlot
from app.models.opportunity import (
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.services.admin_agent_access import admin_agent_access_service
from app.services.commercial.meeting_read_models import (
    MeetingReadNotFoundError,
    MeetingReadService,
)
from app.services.commercial.meetings import (
    InvalidMeetingCommandError,
    MeetingActor,
    MeetingIdempotencyConflictError,
    MeetingService,
    MeetingVersionConflictError,
    ProposedSlot,
)
from app.services.commercial.opportunities import OpportunityService

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class MeetingContext:
    agent_id: UUID
    admin_id: UUID
    principal_id: UUID
    identity_id: UUID
    conversation_id: UUID
    contact_id: UUID
    opportunity_id: UUID


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def meeting_context() -> MeetingContext:
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        agent = _agent(suffix)
        admin = AdminUser(
            email=f"meeting-{suffix}@example.test",
            hashed_password="not-used",
            name="Meeting operator",
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        principal = Principal(display_name="Meeting test principal")
        db.add_all([agent, admin, principal])
        await db.flush()
        await admin_agent_access_service.set_grant(
            db,
            admin_user_id=admin.id,
            role_key=admin.role,
            agent_id=agent.id,
            permissions=["*"],
            created_by="integration-test",
        )
        identity = ChannelIdentity(
            principal_id=principal.id,
            channel="web",
            route_key=f"meeting-{suffix}",
            external_subject=f"visitor-{suffix}",
            verified=False,
        )
        db.add(identity)
        await db.flush()
        conversation = ChatConversation(
            agent_id=agent.id,
            automation_agent_id=agent.id,
            principal_id=principal.id,
            channel="web",
            route_key=identity.route_key,
            external_thread_id=f"thread-{suffix}",
            transcript_consent=True,
            consent_version="test-v1",
        )
        contact = Contact(
            principal_id=principal.id,
            created_by_agent_id=agent.id,
            status="active",
        )
        db.add_all([conversation, contact])
        await db.flush()
        opportunity = await OpportunityService().create(
            db,
            contact_id=contact.id,
            source_conversation_id=conversation.id,
            created_by_agent_id=agent.id,
            assigned_agent_id=agent.id,
            assigned_operator_id=admin.id,
            title="Meeting integration opportunity",
            summary=None,
            correlation_id=f"meeting-opportunity-{suffix}",
            idempotency_key=f"meeting-opportunity-{suffix}",
        )
        await db.commit()
        context = MeetingContext(
            agent_id=agent.id,
            admin_id=admin.id,
            principal_id=principal.id,
            identity_id=identity.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            opportunity_id=opportunity.opportunity.id,
        )

    try:
        yield context
    finally:
        await _cleanup(context)


@pytest.mark.asyncio
async def test_manual_meeting_flow_is_idempotent_versioned_and_audited(
    meeting_context: MeetingContext,
) -> None:
    context = meeting_context
    service = MeetingService()
    actor = MeetingActor(admin_id=context.admin_id)
    starts_at = datetime.now(UTC) + timedelta(days=2)

    async with AsyncSessionLocal() as db:
        created = await service.create(
            db,
            agent_id=context.agent_id,
            opportunity_id=context.opportunity_id,
            conversation_id=context.conversation_id,
            actor=actor,
            correlation_id="meeting-create",
            idempotency_key="meeting-create",
        )
        repeated = await service.create(
            db,
            agent_id=context.agent_id,
            opportunity_id=context.opportunity_id,
            conversation_id=context.conversation_id,
            actor=actor,
            correlation_id="meeting-create-retry",
            idempotency_key="meeting-create",
        )
        assert created.created is True
        assert repeated.created is False
        meeting_id = created.meeting.id
        with pytest.raises(MeetingIdempotencyConflictError):
            await service.create(
                db,
                agent_id=context.agent_id,
                opportunity_id=context.opportunity_id,
                conversation_id=None,
                actor=actor,
                correlation_id="meeting-create-collision",
                idempotency_key="meeting-create",
            )
        await db.commit()

    async with AsyncSessionLocal() as db:
        proposed = await service.propose_slots(
            db,
            agent_id=context.agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=0,
            slots=[
                ProposedSlot(
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(hours=1),
                    timezone="America/Argentina/Salta",
                ),
                ProposedSlot(
                    starts_at=starts_at + timedelta(days=1),
                    ends_at=starts_at + timedelta(days=1, hours=1),
                    timezone="America/Argentina/Salta",
                ),
            ],
            reason="Two agreed alternatives.",
            correlation_id="meeting-proposal",
            idempotency_key="meeting-proposal",
        )
        assert proposed.meeting.state_version == 1
        slots = list(
            (
                await db.execute(
                    select(MeetingSlot)
                    .where(MeetingSlot.meeting_id == meeting_id)
                    .order_by(MeetingSlot.position)
                )
            )
            .scalars()
            .all()
        )
        assert [slot.position for slot in slots] == [1, 2]
        slot_id = slots[0].id
        await service.mark_awaiting_response(
            db,
            agent_id=context.agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=1,
            reason=None,
            correlation_id="meeting-awaiting",
            idempotency_key="meeting-awaiting",
        )
        await service.select_slot(
            db,
            agent_id=context.agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=2,
            slot_id=slot_id,
            reason=None,
            correlation_id="meeting-select",
            idempotency_key="meeting-select",
        )
        scheduled = await service.schedule_manual(
            db,
            agent_id=context.agent_id,
            meeting_id=meeting_id,
            actor_admin_id=context.admin_id,
            expected_version=3,
            expected_opportunity_version=0,
            slot_id=slot_id,
            evidence_type="operator_confirmation",
            evidence_reference="internal-record-001",
            reason="Confirmed during manual contact.",
            correlation_id="meeting-schedule",
            idempotency_key="meeting-schedule",
        )
        assert scheduled.meeting.status == "scheduled"
        assert scheduled.opportunity.stage == "meeting_scheduled"
        assert scheduled.opportunity.control_version == 1
        with pytest.raises(MeetingVersionConflictError):
            await service.cancel(
                db,
                agent_id=context.agent_id,
                meeting_id=meeting_id,
                actor=actor,
                expected_version=2,
                reason=None,
                correlation_id="meeting-stale",
                idempotency_key="meeting-stale",
            )
        cancelled = await service.cancel(
            db,
            agent_id=context.agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=4,
            reason="Client cancelled.",
            correlation_id="meeting-cancel",
            idempotency_key="meeting-cancel",
        )
        assert cancelled.meeting.status == "cancelled"
        assert cancelled.opportunity.stage == "meeting_scheduled"
        await OpportunityService().transition_stage(
            db,
            opportunity_id=context.opportunity_id,
            actor_agent_id=context.agent_id,
            actor_operator_id=context.admin_id,
            target_stage="paused",
            expected_version=1,
            reason="Pause after meeting cancellation.",
            correlation_id="meeting-opportunity-pause",
            idempotency_key="meeting-opportunity-pause",
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        detail = await MeetingReadService().get_meeting(
            db,
            agent_id=context.agent_id,
            meeting_id=meeting_id,
        )
        assert detail.state_version == 5
        assert detail.opportunity_control_version == 2
        assert [event.state_version for event in detail.events] == list(range(6))
        manual_event = next(
            event for event in detail.events if event.event_type == "scheduled_manual"
        )
        assert manual_event.actor_admin_id == context.admin_id
        assert manual_event.evidence_recorded is True
        assert not hasattr(manual_event, "evidence_reference")
        assert detail.events[-1].opportunity_control_version == 1
        page = await MeetingReadService().list_meetings(
            db,
            agent_id=context.agent_id,
            opportunity_id=context.opportunity_id,
            status="cancelled",
            limit=10,
            offset=0,
        )
        assert [item.id for item in page.items] == [meeting_id]
        assert page.items[0].opportunity_control_version == 2


@pytest.mark.asyncio
async def test_automation_is_fenced_by_human_control_and_agent_scope(
    meeting_context: MeetingContext,
) -> None:
    context = meeting_context
    service = MeetingService()
    actor = MeetingActor(
        agent_id=context.agent_id,
        expected_opportunity_version=0,
        expected_conversation_control_version=0,
        expected_conversation_automation_version=0,
    )
    foreign_agent_id = None

    async with AsyncSessionLocal() as db:
        created = await service.create(
            db,
            agent_id=context.agent_id,
            opportunity_id=context.opportunity_id,
            conversation_id=context.conversation_id,
            actor=actor,
            correlation_id="automation-meeting-create",
            idempotency_key="automation-meeting-create",
        )
        conversation = await db.get(ChatConversation, context.conversation_id)
        conversation.control_mode = "human"
        conversation.control_version += 1
        conversation.assigned_admin_id = context.admin_id
        replayed = await service.create(
            db,
            agent_id=context.agent_id,
            opportunity_id=context.opportunity_id,
            conversation_id=context.conversation_id,
            actor=actor,
            correlation_id="automation-meeting-create-retry",
            idempotency_key="automation-meeting-create",
        )
        assert replayed.created is False
        with pytest.raises(InvalidMeetingCommandError, match="control"):
            await service.propose_slots(
                db,
                agent_id=context.agent_id,
                meeting_id=created.meeting.id,
                actor=actor,
                expected_version=0,
                slots=[
                    ProposedSlot(
                        starts_at=datetime.now(UTC) + timedelta(days=1),
                        ends_at=datetime.now(UTC) + timedelta(days=1, hours=1),
                        timezone="UTC",
                    )
                ],
                reason=None,
                correlation_id="automation-meeting-blocked",
                idempotency_key="automation-meeting-blocked",
            )
        foreign = _agent(uuid4().hex)
        db.add(foreign)
        await db.flush()
        foreign_agent_id = foreign.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(MeetingReadNotFoundError):
            await MeetingReadService().get_meeting(
                db,
                agent_id=foreign_agent_id,
                meeting_id=created.meeting.id,
            )
        await db.execute(
            delete(AgentProfile).where(AgentProfile.id == foreign_agent_id)
        )
        await db.commit()


def _agent(suffix: str) -> AgentProfile:
    return AgentProfile(
        name=f"Meeting agent {suffix}",
        slug=f"meeting-agent-{suffix}",
        version=1,
        is_active=True,
        is_public=False,
        retention_days=30,
        description=None,
        prompt_identity="Test identity",
        prompt_domain="Test domain",
        prompt_guardrails="Test guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
        created_by="integration-test",
    )


async def _cleanup(context: MeetingContext) -> None:
    async with AsyncSessionLocal() as db:
        meeting_ids = select(Meeting.id).where(
            Meeting.opportunity_id == context.opportunity_id
        )
        await db.execute(
            update(Meeting)
            .where(Meeting.opportunity_id == context.opportunity_id)
            .values(selected_slot_id=None)
        )
        await db.execute(
            delete(MeetingEvent).where(MeetingEvent.meeting_id.in_(meeting_ids))
        )
        await db.execute(
            delete(MeetingSlot).where(MeetingSlot.meeting_id.in_(meeting_ids))
        )
        await db.execute(
            delete(Meeting).where(Meeting.opportunity_id == context.opportunity_id)
        )
        for model in (
            OpportunityConversation,
            OpportunityOwnershipEvent,
            OpportunityStageEvent,
        ):
            await db.execute(
                delete(model).where(model.opportunity_id == context.opportunity_id)
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
            delete(AdminAgentGrant).where(
                AdminAgentGrant.admin_user_id == context.admin_id
            )
        )
        await db.execute(delete(AdminUser).where(AdminUser.id == context.admin_id))
        await db.execute(
            delete(AgentProfile).where(AgentProfile.id == context.agent_id)
        )
        await db.commit()
