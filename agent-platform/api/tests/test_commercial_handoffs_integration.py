"""PostgreSQL coverage for deterministic commercial handoff coordination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_handoff_route import AgentHandoffRoute
from app.models.agent_profile import AgentProfile
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.opportunity import (
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.services.commercial.handoffs import (
    CommercialHandoffConsentRequiredError,
    CommercialHandoffContactEvidenceError,
    CommercialHandoffCoordinator,
    CommercialHandoffError,
    CommercialHandoffRouteRequiredError,
)
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentService,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class CommercialHandoffContext:
    source_agent_id: UUID
    target_agent_id: UUID
    principal_id: UUID
    conversation_id: UUID
    identity_id: UUID
    contact_id: UUID
    contact_point_id: UUID
    consent_id: UUID
    route_id: UUID
    admin_id: UUID
    role_key: str


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def commercial_handoff_context() -> CommercialHandoffContext:
    suffix = uuid4().hex
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        role = AdminRole(
            key=f"commercial-handoff-{suffix}"[:40],
            name="Commercial handoff test role",
            description=None,
            permissions=["runtime.read", "runtime.manage"],
            is_active=True,
            is_system=False,
        )
        admin = AdminUser(
            email=f"commercial-handoff-{suffix}@example.test",
            hashed_password="not-used",
            name="Commercial handoff test admin",
            role=role.key,
            is_active=True,
            must_change_password=False,
        )
        source_agent = _agent(slug=f"handoff-source-{suffix}")
        target_agent = _agent(slug=f"handoff-target-{suffix}")
        principal = Principal(display_name="Commercial handoff lead")
        db.add_all([role, admin, source_agent, target_agent, principal])
        await db.flush()

        identity = ChannelIdentity(
            principal_id=principal.id,
            channel="web",
            route_key=f"commercial-handoff-{suffix}",
            external_subject=f"visitor-{suffix}",
            verified=False,
        )
        db.add(identity)
        await db.flush()
        conversation = ChatConversation(
            agent_id=source_agent.id,
            principal_id=principal.id,
            channel="web",
            route_key=identity.route_key,
            external_thread_id=f"thread-{suffix}",
            transcript_consent=True,
            consent_version="commercial-v1",
        )
        contact = Contact(
            principal_id=principal.id,
            created_by_agent_id=source_agent.id,
            status="active",
            company_name="Example Company",
        )
        db.add_all([conversation, contact])
        await db.flush()
        point = ContactPoint(
            contact_id=contact.id,
            kind="email",
            ciphertext="gAAAAA" + ("x" * 80),
            lookup_hmac="c" * 64,
            masked_value="l***@example.com",
            verification_status="unverified",
            source_conversation_id=conversation.id,
            source_channel_identity_id=identity.id,
        )
        route = AgentHandoffRoute(
            source_agent_id=source_agent.id,
            target_agent_id=target_agent.id,
            trigger="quote_requested",
            is_active=True,
            control_version=0,
            created_by_admin_id=admin.id,
            updated_by_admin_id=admin.id,
        )
        db.add_all([point, route])
        await db.flush()
        consent = ConsentRecord(
            id=uuid4(),
            principal_id=principal.id,
            contact_id=contact.id,
            contact_point_id=point.id,
            agent_id=source_agent.id,
            purpose="quote_delivery",
            action="grant",
            policy_version="commercial-v1",
            channel="web",
            locale="es-AR",
            source_conversation_id=conversation.id,
            source_channel_identity_id=identity.id,
            correlation_id="commercial-handoff-consent",
            idempotency_key=f"commercial-handoff-consent-{suffix}",
            command_hash="d" * 64,
            occurred_at=now,
        )
        db.add(consent)
        await db.commit()
        context = CommercialHandoffContext(
            source_agent_id=source_agent.id,
            target_agent_id=target_agent.id,
            principal_id=principal.id,
            conversation_id=conversation.id,
            identity_id=identity.id,
            contact_id=contact.id,
            contact_point_id=point.id,
            consent_id=consent.id,
            route_id=route.id,
            admin_id=admin.id,
            role_key=role.key,
        )

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            opportunity_ids = select(Opportunity.id).where(
                Opportunity.contact_id == context.contact_id
            )
            await db.execute(
                delete(ConversationAutomationAssignmentEvent).where(
                    ConversationAutomationAssignmentEvent.conversation_id
                    == context.conversation_id
                )
            )
            for model in (
                OpportunityConversation,
                OpportunityOwnershipEvent,
                OpportunityStageEvent,
            ):
                await db.execute(
                    delete(model).where(model.opportunity_id.in_(opportunity_ids))
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
                delete(AgentHandoffRoute).where(
                    AgentHandoffRoute.id == context.route_id
                )
            )
            await db.execute(
                delete(ContactPoint).where(ContactPoint.id == context.contact_point_id)
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
            await db.execute(
                delete(Principal).where(Principal.id == context.principal_id)
            )
            await db.execute(delete(AdminUser).where(AdminUser.id == context.admin_id))
            await db.execute(delete(AdminRole).where(AdminRole.key == context.role_key))
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_(
                        [context.source_agent_id, context.target_agent_id]
                    )
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_quote_handoff_assigns_specialist_without_moving_route_owner(
    commercial_handoff_context: CommercialHandoffContext,
) -> None:
    context = commercial_handoff_context
    coordinator = CommercialHandoffCoordinator()

    async with AsyncSessionLocal() as db:
        created = await coordinator.quote_requested(
            db,
            source_agent_id=context.source_agent_id,
            conversation_id=context.conversation_id,
            contact_id=context.contact_id,
            contact_point_id=context.contact_point_id,
            title="Custom software platform",
            summary="Qualified lead requested a quote.",
            correlation_id="commercial-handoff-create",
            idempotency_key="commercial-handoff-create",
        )
        assert created.created is True
        assert created.opportunity.created_by_agent_id == context.source_agent_id
        assert created.opportunity.assigned_agent_id == context.target_agent_id
        opportunity_id = created.opportunity.id
        conversation = await db.get(ChatConversation, context.conversation_id)
        assert conversation is not None
        assert conversation.agent_id == context.source_agent_id
        assert conversation.automation_agent_id == context.target_agent_id
        assert conversation.automation_version == 1
        await db.commit()

    async with AsyncSessionLocal() as db:
        await ConversationAutomationAssignmentService().assign(
            db,
            conversation_id=context.conversation_id,
            routing_agent_id=context.source_agent_id,
            target_agent_id=context.source_agent_id,
            expected_automation_version=1,
            actor_agent_id=context.target_agent_id,
            actor_admin_id=None,
            trigger="manual_test_reassignment",
            opportunity_id=None,
            correlation_id="later-reassignment",
            idempotency_key="later-reassignment",
            reason="prove retry stability",
        )
        route = await db.get(AgentHandoffRoute, context.route_id)
        assert route is not None
        route.is_active = False
        await db.flush()
        repeated = await coordinator.quote_requested(
            db,
            source_agent_id=context.source_agent_id,
            conversation_id=context.conversation_id,
            contact_id=context.contact_id,
            contact_point_id=context.contact_point_id,
            title="Custom software platform",
            summary="Qualified lead requested a quote.",
            correlation_id="commercial-handoff-retry",
            idempotency_key="commercial-handoff-create",
        )
        assert repeated.created is False
        assert repeated.opportunity.id == opportunity_id
        await db.commit()

    async with AsyncSessionLocal() as db:
        conversation = await db.get(ChatConversation, context.conversation_id)
        opportunity_count = (
            await db.execute(
                select(func.count(Opportunity.id)).where(
                    Opportunity.contact_id == context.contact_id
                )
            )
        ).scalar_one()
        assert conversation is not None
        assert conversation.agent_id == context.source_agent_id
        assert conversation.automation_agent_id == context.source_agent_id
        assert conversation.automation_version == 2
        assert opportunity_count == 1


@pytest.mark.asyncio
async def test_quote_handoff_rolls_back_opportunity_when_assignment_fails(
    commercial_handoff_context: CommercialHandoffContext,
) -> None:
    context = commercial_handoff_context

    class _FailingAssignments:
        async def assign(self, *_args, **_kwargs):
            raise CommercialHandoffError("assignment failed")

    coordinator = CommercialHandoffCoordinator(
        automation_assignments=_FailingAssignments()
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(CommercialHandoffError, match="assignment failed"):
            async with db.begin():
                await _execute_handoff(
                    coordinator,
                    db,
                    context,
                    key="atomic-assignment-failure",
                )

    async with AsyncSessionLocal() as db:
        opportunity_count = (
            await db.execute(
                select(func.count(Opportunity.id)).where(
                    Opportunity.contact_id == context.contact_id
                )
            )
        ).scalar_one()
        conversation = await db.get(ChatConversation, context.conversation_id)
        assert opportunity_count == 0
        assert conversation is not None
        assert conversation.automation_agent_id == context.source_agent_id
        assert conversation.automation_version == 0


@pytest.mark.asyncio
async def test_quote_handoff_fails_closed_without_route_contact_or_consent(
    commercial_handoff_context: CommercialHandoffContext,
) -> None:
    context = commercial_handoff_context
    coordinator = CommercialHandoffCoordinator()

    async with AsyncSessionLocal() as db:
        route = await db.get(AgentHandoffRoute, context.route_id)
        assert route is not None
        route.is_active = False
        await db.flush()
        with pytest.raises(CommercialHandoffRouteRequiredError):
            await _execute_handoff(coordinator, db, context, key="missing-route")
        await db.rollback()

    async with AsyncSessionLocal() as db:
        with pytest.raises(CommercialHandoffContactEvidenceError):
            await coordinator.quote_requested(
                db,
                source_agent_id=context.source_agent_id,
                conversation_id=context.conversation_id,
                contact_id=uuid4(),
                contact_point_id=context.contact_point_id,
                title="Custom software platform",
                summary=None,
                correlation_id="mismatched-contact",
                idempotency_key="mismatched-contact",
            )

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ConsentRecord).where(ConsentRecord.id == context.consent_id)
        )
        await db.flush()
        with pytest.raises(CommercialHandoffConsentRequiredError):
            await _execute_handoff(coordinator, db, context, key="missing-consent")
        opportunity_count = (
            await db.execute(
                select(func.count(Opportunity.id)).where(
                    Opportunity.contact_id == context.contact_id
                )
            )
        ).scalar_one()
        assert opportunity_count == 0
        await db.rollback()


async def _execute_handoff(
    coordinator: CommercialHandoffCoordinator,
    db,
    context: CommercialHandoffContext,
    *,
    key: str,
):
    return await coordinator.quote_requested(
        db,
        source_agent_id=context.source_agent_id,
        conversation_id=context.conversation_id,
        contact_id=context.contact_id,
        contact_point_id=context.contact_point_id,
        title="Custom software platform",
        summary=None,
        correlation_id=key,
        idempotency_key=key,
    )


def _agent(*, slug: str) -> AgentProfile:
    return AgentProfile(
        name=slug,
        slug=slug,
        version=1,
        is_active=True,
        is_public=False,
        retention_days=30,
        prompt_identity="Commercial handoff identity",
        prompt_domain="Commercial handoff domain",
        prompt_guardrails="Commercial handoff guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
    )
