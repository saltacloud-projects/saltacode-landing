"""PostgreSQL coverage for conversation automation assignment epochs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.agent_profile import AgentProfile
from app.models.contact import Contact
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.opportunity import Opportunity, OpportunityConversation
from app.models.platform import ChatConversation, Principal
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentClosedError,
    ConversationAutomationAssignmentIdempotencyError,
    ConversationAutomationAssignmentInactiveAgentError,
    ConversationAutomationAssignmentService,
    ConversationAutomationAssignmentValidationError,
    ConversationAutomationAssignmentVersionConflictError,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class AssignmentContext:
    conversation_id: UUID
    routing_agent_id: UUID
    target_agent_id: UUID
    alternate_agent_id: UUID
    inactive_agent_id: UUID
    principal_id: UUID
    contact_id: UUID
    opportunity_id: UUID


def _agent(label: str, *, active: bool = True) -> AgentProfile:
    suffix = uuid4().hex
    return AgentProfile(
        name=f"Automation {label}",
        slug=f"automation-{label}-{suffix}",
        version=1,
        is_active=active,
        is_public=False,
        retention_days=30,
        prompt_identity="Identity",
        prompt_domain="Domain",
        prompt_guardrails="Guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
        created_by="integration-test",
    )


@pytest.fixture
async def assignment_context() -> AssignmentContext:
    async with AsyncSessionLocal() as db:
        routing = _agent("routing")
        target = _agent("target")
        alternate = _agent("alternate")
        inactive = _agent("inactive", active=False)
        principal = Principal(kind="anonymous", is_active=True, attributes={})
        db.add_all([routing, target, alternate, inactive, principal])
        await db.flush()
        conversation = ChatConversation(
            agent_id=routing.id,
            principal_id=principal.id,
            channel="web",
            external_thread_id=f"assignment-{uuid4()}",
            route_key=f"assignment-{uuid4().hex}",
            status="active",
            control_mode="automated",
            control_version=0,
            next_outbound_sequence=1,
            next_event_sequence=1,
            transcript_consent=False,
            attributes={},
        )
        contact = Contact(
            principal_id=principal.id,
            created_by_agent_id=routing.id,
            status="active",
        )
        db.add_all([conversation, contact])
        await db.flush()
        opportunity = Opportunity(
            contact_id=contact.id,
            created_by_agent_id=routing.id,
            assigned_agent_id=target.id,
            assigned_operator_id=None,
            stage="new",
            control_version=0,
            title="Automation assignment",
            summary=None,
            correlation_id="assignment-fixture",
            idempotency_key=f"assignment-{uuid4()}",
            command_hash="0" * 64,
        )
        db.add(opportunity)
        await db.flush()
        db.add(
            OpportunityConversation(
                opportunity_id=opportunity.id,
                conversation_id=conversation.id,
                linked_by_agent_id=routing.id,
                linked_by_operator_id=None,
                correlation_id="assignment-fixture",
                idempotency_key=f"assignment-link-{uuid4()}",
                command_hash="1" * 64,
            )
        )
        await db.commit()
        context = AssignmentContext(
            conversation_id=conversation.id,
            routing_agent_id=routing.id,
            target_agent_id=target.id,
            alternate_agent_id=alternate.id,
            inactive_agent_id=inactive.id,
            principal_id=principal.id,
            contact_id=contact.id,
            opportunity_id=opportunity.id,
        )

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id == context.conversation_id
                )
            )
            await db.execute(
                delete(OpportunityConversation).where(
                    OpportunityConversation.opportunity_id == context.opportunity_id
                )
            )
            await db.execute(
                delete(Opportunity).where(Opportunity.id == context.opportunity_id)
            )
            await db.execute(delete(Contact).where(Contact.id == context.contact_id))
            await db.execute(
                delete(Principal).where(Principal.id == context.principal_id)
            )
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_(
                        [
                            context.routing_agent_id,
                            context.target_agent_id,
                            context.alternate_agent_id,
                            context.inactive_agent_id,
                        ]
                    )
                )
            )
            await db.commit()


def _command(
    context: AssignmentContext,
    *,
    target_agent_id: UUID | None = None,
    expected_version: int = 0,
    idempotency_key: str = "assignment-1",
    opportunity_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "conversation_id": context.conversation_id,
        "routing_agent_id": context.routing_agent_id,
        "target_agent_id": target_agent_id or context.target_agent_id,
        "expected_automation_version": expected_version,
        "actor_agent_id": context.routing_agent_id,
        "actor_admin_id": None,
        "trigger": "quote_requested",
        "opportunity_id": opportunity_id,
        "correlation_id": "assignment-correlation",
        "idempotency_key": idempotency_key,
        "reason": "Commercial specialist requested",
    }


@pytest.mark.asyncio
async def test_assignment_is_idempotent_audited_and_keeps_routing_owner(
    assignment_context: AssignmentContext,
) -> None:
    context = assignment_context
    service = ConversationAutomationAssignmentService()
    command = _command(
        context,
        opportunity_id=context.opportunity_id,
    )

    async with AsyncSessionLocal() as db:
        created = await service.assign(db, **command)
        await db.commit()
    async with AsyncSessionLocal() as db:
        duplicate = await service.assign(db, **command)
        await db.commit()
        conversation = await db.get(ChatConversation, context.conversation_id)
        events = list(
            (
                await db.execute(
                    select(ConversationAutomationAssignmentEvent).where(
                        ConversationAutomationAssignmentEvent.conversation_id
                        == context.conversation_id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert created.applied is True
    assert duplicate.duplicate is True
    assert duplicate.applied is False
    assert conversation.agent_id == context.routing_agent_id
    assert conversation.automation_agent_id == context.target_agent_id
    assert conversation.automation_version == 1
    assert len(events) == 1
    assert events[0].opportunity_id == context.opportunity_id


@pytest.mark.asyncio
async def test_no_op_is_append_only_without_incrementing_epoch(
    assignment_context: AssignmentContext,
) -> None:
    context = assignment_context
    async with AsyncSessionLocal() as db:
        result = await ConversationAutomationAssignmentService().assign(
            db,
            **_command(
                context,
                target_agent_id=context.routing_agent_id,
                idempotency_key="assignment-no-op",
            ),
        )
        await db.commit()

    assert result.duplicate is False
    assert result.applied is False
    assert result.event.automation_version == 0
    assert result.event.from_automation_agent_id == context.routing_agent_id
    assert result.event.to_automation_agent_id == context.routing_agent_id


@pytest.mark.asyncio
async def test_conflicts_closed_inactive_and_foreign_opportunity_fail_closed(
    assignment_context: AssignmentContext,
) -> None:
    context = assignment_context
    service = ConversationAutomationAssignmentService()
    command = _command(context)
    async with AsyncSessionLocal() as db:
        await service.assign(db, **command)
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(ConversationAutomationAssignmentIdempotencyError):
            await service.assign(
                db,
                **{
                    **command,
                    "target_agent_id": context.alternate_agent_id,
                },
            )

        with pytest.raises(ConversationAutomationAssignmentVersionConflictError):
            await service.assign(
                db,
                **_command(
                    context,
                    target_agent_id=context.alternate_agent_id,
                    idempotency_key="assignment-stale",
                ),
            )

        with pytest.raises(ConversationAutomationAssignmentInactiveAgentError):
            await service.assign(
                db,
                **_command(
                    context,
                    target_agent_id=context.inactive_agent_id,
                    expected_version=1,
                    idempotency_key="assignment-inactive",
                ),
            )

        with pytest.raises(ConversationAutomationAssignmentValidationError):
            await service.assign(
                db,
                **_command(
                    context,
                    target_agent_id=context.alternate_agent_id,
                    expected_version=1,
                    idempotency_key="assignment-foreign-opportunity",
                    opportunity_id=context.opportunity_id,
                ),
            )

        conversation = await db.get(ChatConversation, context.conversation_id)
        conversation.status = "closed"
        conversation.control_mode = "closed"
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(ConversationAutomationAssignmentClosedError):
            await service.assign(
                db,
                **_command(
                    context,
                    expected_version=1,
                    idempotency_key="assignment-closed",
                ),
            )


@pytest.mark.asyncio
async def test_concurrent_duplicate_creates_one_applied_event(
    assignment_context: AssignmentContext,
) -> None:
    context = assignment_context
    command = _command(context, idempotency_key="assignment-concurrent")

    async def assign_once():
        async with AsyncSessionLocal() as db:
            result = await ConversationAutomationAssignmentService().assign(
                db,
                **command,
            )
            await db.commit()
            return result

    results = await asyncio.gather(assign_once(), assign_once())

    assert sorted(result.duplicate for result in results) == [False, True]
    async with AsyncSessionLocal() as db:
        events = list(
            (
                await db.execute(
                    select(ConversationAutomationAssignmentEvent).where(
                        ConversationAutomationAssignmentEvent.conversation_id
                        == context.conversation_id,
                        ConversationAutomationAssignmentEvent.idempotency_key
                        == "assignment-concurrent",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
    assert events[0].applied is True


@pytest.mark.asyncio
async def test_concurrent_distinct_commands_advance_only_one_epoch(
    assignment_context: AssignmentContext,
) -> None:
    context = assignment_context

    async def assign_once(*, target_agent_id: UUID, idempotency_key: str):
        async with AsyncSessionLocal() as db:
            try:
                result = await ConversationAutomationAssignmentService().assign(
                    db,
                    **_command(
                        context,
                        target_agent_id=target_agent_id,
                        idempotency_key=idempotency_key,
                    ),
                )
                await db.commit()
                return result
            except ConversationAutomationAssignmentVersionConflictError as error:
                await db.rollback()
                return error

    results = await asyncio.gather(
        assign_once(
            target_agent_id=context.target_agent_id,
            idempotency_key="assignment-race-target",
        ),
        assign_once(
            target_agent_id=context.alternate_agent_id,
            idempotency_key="assignment-race-alternate",
        ),
    )

    assert (
        sum(
            isinstance(result, ConversationAutomationAssignmentVersionConflictError)
            for result in results
        )
        == 1
    )
    async with AsyncSessionLocal() as db:
        conversation = await db.get(ChatConversation, context.conversation_id)
        applied_events = list(
            (
                await db.execute(
                    select(ConversationAutomationAssignmentEvent).where(
                        ConversationAutomationAssignmentEvent.conversation_id
                        == context.conversation_id,
                        ConversationAutomationAssignmentEvent.applied.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert conversation.automation_version == 1
    assert len(applied_events) == 1
