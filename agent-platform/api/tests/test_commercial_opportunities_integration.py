"""PostgreSQL integration coverage for commercial ownership and quotes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import (
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.models.quote import QuoteRequest, QuoteVersion
from app.services.commercial.follow_ups import (
    FollowUpConsentRequiredError,
    FollowUpKind,
    FollowUpService,
    FollowUpStatus,
    FollowUpVersionConflictError,
    InvalidFollowUpCommandError,
)
from app.services.commercial.opportunities import (
    OpportunityNotFoundError,
    OpportunityService,
    OpportunityStage,
)
from app.services.commercial.quotes import InvalidQuoteCommandError, QuoteService
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentService,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class CommercialDossierContext:
    intake_agent_id: UUID
    opportunity_agent_id: UUID
    principal_id: UUID
    conversation_id: UUID
    identity_id: UUID
    contact_id: UUID
    contact_point_id: UUID


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def commercial_dossier() -> CommercialDossierContext:
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        intake_agent = _agent(slug=f"commercial-intake-{suffix}")
        opportunity_agent = _agent(slug=f"commercial-opportunity-{suffix}")
        principal = Principal(display_name="Commercial dossier")
        db.add_all([intake_agent, opportunity_agent, principal])
        await db.flush()
        identity = ChannelIdentity(
            principal_id=principal.id,
            channel="web",
            route_key=f"commercial-{suffix}",
            external_subject=f"visitor-{suffix}",
            verified=False,
        )
        db.add(identity)
        await db.flush()
        conversation = ChatConversation(
            agent_id=intake_agent.id,
            principal_id=principal.id,
            channel="web",
            route_key=identity.route_key,
            external_thread_id=f"thread-{suffix}",
            transcript_consent=True,
            consent_version="test-v1",
        )
        contact = Contact(
            principal_id=principal.id,
            created_by_agent_id=intake_agent.id,
            status="active",
            company_name="Example Company",
        )
        db.add_all([conversation, contact])
        await db.flush()
        point = ContactPoint(
            contact_id=contact.id,
            kind="email",
            ciphertext="gAAAAA" + ("x" * 80),
            lookup_hmac="a" * 64,
            masked_value="l***@example.com",
            verification_status="verified",
            verified_at=datetime.now(UTC),
            source_conversation_id=conversation.id,
            source_channel_identity_id=identity.id,
        )
        db.add(point)
        await db.commit()
        context = CommercialDossierContext(
            intake_agent_id=intake_agent.id,
            opportunity_agent_id=opportunity_agent.id,
            principal_id=principal.id,
            conversation_id=conversation.id,
            identity_id=identity.id,
            contact_id=contact.id,
            contact_point_id=point.id,
        )

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.opportunity_id.in_(
                        select(Opportunity.id).where(
                            Opportunity.contact_id == context.contact_id
                        )
                    )
                )
            )
            await db.execute(
                delete(FollowUpTask).where(
                    FollowUpTask.opportunity_id.in_(
                        select(Opportunity.id).where(
                            Opportunity.contact_id == context.contact_id
                        )
                    )
                )
            )
            await db.execute(
                delete(QuoteVersion).where(
                    QuoteVersion.quote_request_id.in_(
                        select(QuoteRequest.id)
                        .join(
                            Opportunity,
                            Opportunity.id == QuoteRequest.opportunity_id,
                        )
                        .where(Opportunity.contact_id == context.contact_id)
                    )
                )
            )
            await db.execute(
                delete(QuoteRequest).where(
                    QuoteRequest.opportunity_id.in_(
                        select(Opportunity.id).where(
                            Opportunity.contact_id == context.contact_id
                        )
                    )
                )
            )
            await db.execute(
                delete(CommercialAutomationPolicy).where(
                    CommercialAutomationPolicy.agent_id.in_(
                        [context.intake_agent_id, context.opportunity_agent_id]
                    )
                )
            )
            for model in (
                OpportunityConversation,
                OpportunityOwnershipEvent,
                OpportunityStageEvent,
            ):
                await db.execute(
                    delete(model).where(
                        model.opportunity_id.in_(
                            select(Opportunity.id).where(
                                Opportunity.contact_id == context.contact_id
                            )
                        )
                    )
                )
            await db.execute(
                delete(ConversationAutomationAssignmentEvent).where(
                    ConversationAutomationAssignmentEvent.opportunity_id.in_(
                        select(Opportunity.id).where(
                            Opportunity.contact_id == context.contact_id
                        )
                    )
                )
            )
            await db.execute(
                delete(Opportunity).where(Opportunity.contact_id == context.contact_id)
            )
            await db.execute(
                delete(ConsentRecord).where(
                    ConsentRecord.principal_id == context.principal_id
                )
            )
            await db.execute(
                delete(ContactPoint).where(ContactPoint.id == context.contact_point_id)
            )
            await db.execute(delete(Contact).where(Contact.id == context.contact_id))
            await db.execute(
                delete(ConversationAutomationAssignmentEvent).where(
                    ConversationAutomationAssignmentEvent.conversation_id
                    == context.conversation_id
                )
            )
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id == context.conversation_id
                )
            )
            await db.execute(
                delete(ChannelIdentity).where(ChannelIdentity.id == context.identity_id)
            )
            await db.execute(
                delete(Principal).where(Principal.id == context.principal_id)
            )
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_(
                        [
                            context.intake_agent_id,
                            context.opportunity_agent_id,
                        ]
                    )
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_opportunity_handoff_is_versioned_without_rewriting_chat_owner(
    commercial_dossier: CommercialDossierContext,
) -> None:
    context = commercial_dossier
    service = OpportunityService()

    async with AsyncSessionLocal() as db:
        created = await service.create(
            db,
            contact_id=context.contact_id,
            source_conversation_id=context.conversation_id,
            created_by_agent_id=context.intake_agent_id,
            assigned_agent_id=context.intake_agent_id,
            assigned_operator_id=None,
            title="Custom software project",
            summary="Lead requested a scoped proposal.",
            correlation_id="opportunity-create-1",
            idempotency_key="opportunity-create-1",
        )
        repeated = await service.create(
            db,
            contact_id=context.contact_id,
            source_conversation_id=context.conversation_id,
            created_by_agent_id=context.intake_agent_id,
            assigned_agent_id=context.intake_agent_id,
            assigned_operator_id=None,
            title="Custom software project",
            summary="Lead requested a scoped proposal.",
            correlation_id="opportunity-create-retry",
            idempotency_key="opportunity-create-1",
        )
        assert created.created is True
        assert repeated.created is False
        assert repeated.opportunity.id == created.opportunity.id
        opportunity_id = created.opportunity.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        staged = await service.transition_stage(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.intake_agent_id,
            actor_operator_id=None,
            target_stage=OpportunityStage.QUALIFIED,
            expected_version=0,
            reason="Needs and budget were qualified.",
            correlation_id="opportunity-stage-1",
            idempotency_key="opportunity-stage-1",
        )
        assert staged.opportunity.control_version == 1
        reassigned = await service.reassign(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.intake_agent_id,
            actor_operator_id=None,
            assigned_agent_id=context.opportunity_agent_id,
            assigned_operator_id=None,
            expected_version=1,
            reason="Qualified lead handed to opportunity specialist.",
            correlation_id="opportunity-handoff-1",
            idempotency_key="opportunity-handoff-1",
        )
        assert reassigned.opportunity.control_version == 2
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(OpportunityNotFoundError):
            await service.transition_stage(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.intake_agent_id,
                actor_operator_id=None,
                target_stage=OpportunityStage.PROPOSAL_REQUESTED,
                expected_version=2,
                reason=None,
                correlation_id="opportunity-stage-old-owner",
                idempotency_key="opportunity-stage-old-owner",
            )
        await db.rollback()

        changed = await service.transition_stage(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            target_stage=OpportunityStage.PROPOSAL_REQUESTED,
            expected_version=2,
            reason=None,
            correlation_id="opportunity-stage-2",
            idempotency_key="opportunity-stage-2",
        )
        assert changed.opportunity.control_version == 3
        await db.commit()

    async with AsyncSessionLocal() as db:
        conversation = await db.get(ChatConversation, context.conversation_id)
        opportunity = await db.get(Opportunity, opportunity_id)
        stage_events = (
            await db.execute(
                select(func.count(OpportunityStageEvent.id)).where(
                    OpportunityStageEvent.opportunity_id == opportunity_id
                )
            )
        ).scalar_one()
        ownership_events = (
            await db.execute(
                select(func.count(OpportunityOwnershipEvent.id)).where(
                    OpportunityOwnershipEvent.opportunity_id == opportunity_id
                )
            )
        ).scalar_one()
        assert conversation is not None
        assert conversation.agent_id == context.intake_agent_id
        assert opportunity is not None
        assert opportunity.assigned_agent_id == context.opportunity_agent_id
        assert stage_events == 3
        assert ownership_events == 2

        with pytest.raises(IntegrityError):
            await db.execute(delete(Contact).where(Contact.id == context.contact_id))
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_follow_up_needs_consent_and_quote_needs_authoritative_evidence(
    commercial_dossier: CommercialDossierContext,
) -> None:
    context = commercial_dossier
    opportunities = OpportunityService()
    follow_ups = FollowUpService()
    quotes = QuoteService()
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        opportunity = (
            await opportunities.create(
                db,
                contact_id=context.contact_id,
                source_conversation_id=context.conversation_id,
                created_by_agent_id=context.intake_agent_id,
                assigned_agent_id=context.opportunity_agent_id,
                assigned_operator_id=None,
                title="IT consulting engagement",
                summary=None,
                correlation_id="commercial-create-2",
                idempotency_key="commercial-create-2",
            )
        ).opportunity
        opportunity_id = opportunity.id
        await ConversationAutomationAssignmentService().assign(
            db,
            conversation_id=context.conversation_id,
            routing_agent_id=context.intake_agent_id,
            target_agent_id=context.opportunity_agent_id,
            expected_automation_version=0,
            actor_agent_id=context.intake_agent_id,
            actor_admin_id=None,
            trigger="commercial_test",
            opportunity_id=opportunity_id,
            correlation_id="commercial-assignment-2",
            idempotency_key="commercial-assignment-2",
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        point = await db.get(ContactPoint, context.contact_point_id)
        assert point is not None
        point.verification_status = "unverified"
        with pytest.raises(InvalidFollowUpCommandError):
            await follow_ups.schedule(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                contact_point_id=context.contact_point_id,
                kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
                due_at=now + timedelta(days=2),
                note=None,
                correlation_id="follow-up-unverified-point",
                idempotency_key="follow-up-unverified-point",
                now=now,
            )
        await db.rollback()

    async with AsyncSessionLocal() as db:
        with pytest.raises(FollowUpConsentRequiredError):
            await follow_ups.schedule(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                contact_point_id=context.contact_point_id,
                kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
                due_at=now + timedelta(days=2),
                note="Send the requested follow-up.",
                correlation_id="follow-up-without-consent",
                idempotency_key="follow-up-without-consent",
                now=now,
            )
        await db.rollback()

    async with AsyncSessionLocal() as db:
        consent = ConsentRecord(
            id=uuid4(),
            principal_id=context.principal_id,
            contact_id=context.contact_id,
            contact_point_id=context.contact_point_id,
            agent_id=context.intake_agent_id,
            purpose="commercial_follow_up",
            action="grant",
            policy_version="commercial-v1",
            channel="web",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="consent-grant-1",
            idempotency_key="consent-grant-1",
            command_hash="b" * 64,
            occurred_at=now,
        )
        db.add(consent)
        await db.commit()

    async with AsyncSessionLocal() as db:
        scheduled = await follow_ups.schedule(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            contact_point_id=context.contact_point_id,
            kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
            due_at=now + timedelta(days=2),
            note="Send the requested follow-up.",
            correlation_id="follow-up-1",
            idempotency_key="follow-up-1",
            now=now + timedelta(seconds=1),
        )
        assert scheduled.task.consent_record_id == consent.id
        assert scheduled.task.conversation_id == context.conversation_id
        assert scheduled.task.target_channel == "web"
        assert scheduled.task.scheduled_control_version == 0
        assert scheduled.task.scheduled_automation_version == 1
        assert scheduled.task.scheduled_policy_version == 0
        assert scheduled.task.executed_policy_version is None
        assert scheduled.task.max_attempts == 3
        policy = (
            await db.execute(
                select(CommercialAutomationPolicy).where(
                    CommercialAutomationPolicy.agent_id == context.opportunity_agent_id
                )
            )
        ).scalar_one()
        assert policy.is_enabled is False
        scheduled_events = list(
            (
                await db.execute(
                    select(FollowUpTaskEvent).where(
                        FollowUpTaskEvent.task_id == scheduled.task.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(scheduled_events) == 1
        assert scheduled_events[0].to_status == FollowUpStatus.SCHEDULED
        assert scheduled_events[0].scheduled_policy_version == 0
        with pytest.raises(InvalidFollowUpCommandError):
            await follow_ups.schedule(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                contact_point_id=context.contact_point_id,
                target_channel="email",
                kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
                due_at=now + timedelta(days=2),
                note=None,
                correlation_id="follow-up-cross-channel",
                idempotency_key="follow-up-cross-channel",
                now=now + timedelta(seconds=1),
            )
        deferred = await follow_ups.defer_scheduled(
            db,
            task_id=scheduled.task.id,
            worker_id="follow-up-test-worker",
            available_at=now + timedelta(days=2, minutes=30),
            expected_version=0,
            correlation_id="follow-up-deferred",
            idempotency_key="follow-up-deferred",
            safe_code="quiet_hours",
            occurred_at=now + timedelta(minutes=1),
        )
        assert deferred.status == FollowUpStatus.SCHEDULED
        assert deferred.state_version == 1
        assert deferred.attempts == 0
        assert deferred.executed_policy_version == 0
        deferred_event = (
            await db.execute(
                select(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.task_id == deferred.id,
                    FollowUpTaskEvent.state_version == 1,
                )
            )
        ).scalar_one()
        assert deferred_event.event_type == "deferred"
        assert deferred_event.from_status == FollowUpStatus.SCHEDULED
        assert deferred_event.to_status == FollowUpStatus.SCHEDULED
        assert deferred_event.actor_worker_id == "follow-up-test-worker"
        assert deferred_event.executed_policy_version == 0
        with pytest.raises(InvalidFollowUpCommandError):
            await follow_ups.schedule(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                contact_point_id=context.contact_point_id,
                kind=FollowUpKind.PROPOSAL_REMINDER,
                due_at=now + timedelta(days=3),
                note="Remind the lead about the issued proposal.",
                correlation_id="proposal-reminder-without-quote",
                idempotency_key="proposal-reminder-without-quote",
                now=now + timedelta(seconds=1),
            )
        quote_request = await quotes.request(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            requirements={"service": "consulting", "scope": ["discovery"]},
            correlation_id="quote-request-1",
            idempotency_key="quote-request-1",
        )
        assert quote_request.request.status == "unavailable"
        assert quote_request.request.failure_code == "quote_provider_unavailable"
        request_id = quote_request.request.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(InvalidQuoteCommandError):
            await quotes.issue_authoritative_version(
                db,
                quote_request_id=request_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                expected_version=0,
                authority_name="Quote System",
                authority_version="v1",
                external_reference="quote-100",
                content_hash="A" * 64,
                issued_at=now,
                correlation_id="quote-issue-invalid",
                idempotency_key="quote-issue-invalid",
                recorded_at=now + timedelta(minutes=1),
            )
        await db.rollback()

        issued = await quotes.issue_authoritative_version(
            db,
            quote_request_id=request_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            expected_version=0,
            authority_name="Quote System",
            authority_version="v1",
            external_reference="quote-100",
            content_hash=hashlib.sha256(b"authoritative quote").hexdigest(),
            issued_at=now,
            correlation_id="quote-issue-1",
            idempotency_key="quote-issue-1",
            recorded_at=now + timedelta(minutes=1),
        )
        repeated = await quotes.issue_authoritative_version(
            db,
            quote_request_id=request_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            expected_version=0,
            authority_name="Quote System",
            authority_version="v1",
            external_reference="quote-100",
            content_hash=hashlib.sha256(b"authoritative quote").hexdigest(),
            issued_at=now,
            correlation_id="quote-issue-retry",
            idempotency_key="quote-issue-1",
            recorded_at=now + timedelta(minutes=2),
        )
        assert issued.created is True
        assert repeated.created is False
        assert repeated.version.id == issued.version.id
        assert issued.request.status == "issued"
        assert issued.request.state_version == 1
        reminder = await follow_ups.schedule(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            contact_point_id=context.contact_point_id,
            kind=FollowUpKind.PROPOSAL_REMINDER,
            due_at=now + timedelta(days=3),
            note="Remind the lead about the issued proposal.",
            correlation_id="proposal-reminder-issued",
            idempotency_key="proposal-reminder-issued",
            quote_version_id=issued.version.id,
            now=now + timedelta(seconds=1),
        )
        assert reminder.task.quote_version_id == issued.version.id
        review = await follow_ups.transition(
            db,
            task_id=reminder.task.id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            target_status=FollowUpStatus.REVIEW_REQUIRED,
            expected_version=0,
            correlation_id="proposal-reminder-review",
            idempotency_key="proposal-reminder-review",
            safe_code="operator_requested_review",
            occurred_at=now + timedelta(minutes=2),
        )
        repeated_review = await follow_ups.transition(
            db,
            task_id=reminder.task.id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            target_status=FollowUpStatus.REVIEW_REQUIRED,
            expected_version=0,
            correlation_id="proposal-reminder-review-retry",
            idempotency_key="proposal-reminder-review",
            safe_code="operator_requested_review",
            occurred_at=now + timedelta(minutes=3),
        )
        assert review.state_version == 1
        assert repeated_review.state_version == 1
        reminder_event_count = (
            await db.execute(
                select(func.count(FollowUpTaskEvent.id)).where(
                    FollowUpTaskEvent.task_id == reminder.task.id
                )
            )
        ).scalar_one()
        assert reminder_event_count == 2
        await db.commit()


@pytest.mark.asyncio
async def test_follow_up_fails_closed_for_acting_mismatch_and_ambiguous_links(
    commercial_dossier: CommercialDossierContext,
) -> None:
    context = commercial_dossier
    opportunities = OpportunityService()
    follow_ups = FollowUpService()
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        opportunity = (
            await opportunities.create(
                db,
                contact_id=context.contact_id,
                source_conversation_id=context.conversation_id,
                created_by_agent_id=context.intake_agent_id,
                assigned_agent_id=context.opportunity_agent_id,
                assigned_operator_id=None,
                title="Ambiguous linked channels",
                summary=None,
                correlation_id="commercial-create-ambiguous",
                idempotency_key="commercial-create-ambiguous",
            )
        ).opportunity
        opportunity_id = opportunity.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(InvalidFollowUpCommandError, match="acting agent"):
            await follow_ups.schedule(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                contact_point_id=context.contact_point_id,
                kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
                due_at=now + timedelta(days=1),
                note=None,
                correlation_id="acting-mismatch",
                idempotency_key="acting-mismatch",
                now=now,
            )
        await db.rollback()

    second_conversation_id = uuid4()
    async with AsyncSessionLocal() as db:
        await ConversationAutomationAssignmentService().assign(
            db,
            conversation_id=context.conversation_id,
            routing_agent_id=context.intake_agent_id,
            target_agent_id=context.opportunity_agent_id,
            expected_automation_version=0,
            actor_agent_id=context.intake_agent_id,
            actor_admin_id=None,
            trigger="commercial_test",
            opportunity_id=opportunity_id,
            correlation_id="commercial-assignment-ambiguous",
            idempotency_key="commercial-assignment-ambiguous",
        )
        second_conversation = ChatConversation(
            id=second_conversation_id,
            agent_id=context.intake_agent_id,
            automation_agent_id=context.opportunity_agent_id,
            automation_version=1,
            principal_id=context.principal_id,
            channel="web",
            route_key=f"commercial-secondary-{uuid4().hex}",
            external_thread_id=f"secondary-{uuid4().hex}",
            transcript_consent=True,
            consent_version="test-v1",
        )
        db.add(second_conversation)
        await db.flush()
        db.add(
            OpportunityConversation(
                opportunity_id=opportunity_id,
                conversation_id=second_conversation.id,
                linked_by_agent_id=context.opportunity_agent_id,
                linked_by_operator_id=None,
                correlation_id="second-conversation-link",
                idempotency_key="second-conversation-link",
                command_hash="c" * 64,
            )
        )
        db.add(
            ConsentRecord(
                principal_id=context.principal_id,
                contact_id=context.contact_id,
                contact_point_id=context.contact_point_id,
                agent_id=context.intake_agent_id,
                purpose="commercial_follow_up",
                action="grant",
                policy_version="commercial-v1",
                channel="web",
                locale="es-AR",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
                correlation_id="consent-ambiguous",
                idempotency_key="consent-ambiguous",
                command_hash="d" * 64,
                occurred_at=now,
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(InvalidFollowUpCommandError, match="exactly one"):
            await follow_ups.schedule(
                db,
                opportunity_id=opportunity_id,
                actor_agent_id=context.opportunity_agent_id,
                actor_operator_id=None,
                contact_point_id=context.contact_point_id,
                kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
                due_at=now + timedelta(days=1),
                note=None,
                correlation_id="ambiguous-link",
                idempotency_key="ambiguous-link",
                now=now,
            )
        await db.rollback()

        explicit = await follow_ups.schedule(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=context.opportunity_agent_id,
            actor_operator_id=None,
            contact_point_id=context.contact_point_id,
            conversation_id=context.conversation_id,
            kind=FollowUpKind.COMMERCIAL_FOLLOW_UP,
            due_at=now + timedelta(days=1),
            note=None,
            correlation_id="explicit-link",
            idempotency_key="explicit-link",
            now=now,
        )
        assert explicit.task.conversation_id == context.conversation_id
        await db.commit()


@pytest.mark.asyncio
async def test_commercial_automation_policy_uses_cas_and_starts_disabled(
    commercial_dossier: CommercialDossierContext,
) -> None:
    context = commercial_dossier
    follow_ups = FollowUpService()

    async with AsyncSessionLocal() as db:
        default_policy = await follow_ups.get_policy(
            db,
            agent_id=context.opportunity_agent_id,
        )
        admin_id = (await db.execute(select(AdminUser.id).limit(1))).scalar_one()
        assert default_policy.is_enabled is False
        assert default_policy.version == 0

        configured = await follow_ups.configure_policy(
            db,
            agent_id=context.opportunity_agent_id,
            actor_admin_id=admin_id,
            expected_version=0,
            is_enabled=True,
            allowed_kinds=[FollowUpKind.COMMERCIAL_FOLLOW_UP],
            timezone="America/Argentina/Salta",
            quiet_hours_start=time(21, 0),
            quiet_hours_end=time(8, 0),
            min_interval_seconds=7_200,
            max_attempts=4,
            max_daily_tasks=20,
            max_pending_tasks=80,
        )
        assert configured.is_enabled is True
        assert configured.version == 1
        with pytest.raises(FollowUpVersionConflictError):
            await follow_ups.configure_policy(
                db,
                agent_id=context.opportunity_agent_id,
                actor_admin_id=admin_id,
                expected_version=0,
                is_enabled=False,
                allowed_kinds=[],
                timezone="UTC",
                quiet_hours_start=None,
                quiet_hours_end=None,
                min_interval_seconds=3_600,
                max_attempts=3,
                max_daily_tasks=25,
                max_pending_tasks=100,
            )
        await db.commit()


def _agent(*, slug: str) -> AgentProfile:
    return AgentProfile(
        name=slug,
        slug=slug,
        version=1,
        is_active=True,
        is_public=False,
        retention_days=30,
        prompt_identity="Commercial test identity",
        prompt_domain="Commercial test domain",
        prompt_guardrails="Commercial test guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
    )
