"""Caller-transaction-owned policy for commercial opportunity ownership."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.contact import Contact
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import (
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.platform import ChatConversation
from app.services.commercial._command_policy import CommercialCommandPolicy

_TERMINAL_STAGES = {"won", "lost"}
_OPPORTUNITY_REASSIGNED = "opportunity_reassigned"
_REASSIGNABLE_FOLLOW_UP_STATUSES = (
    "scheduled",
    "dispatch_queued",
    "in_progress",
)


class OpportunityStage(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    PROPOSAL_REQUESTED = "proposal_requested"
    PROPOSAL_PREPARING = "proposal_preparing"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    MEETING_SCHEDULED = "meeting_scheduled"
    WON = "won"
    LOST = "lost"
    PAUSED = "paused"


class CommercialOpportunityError(Exception):
    """Base failure for commercial opportunity policy."""


class OpportunityNotFoundError(CommercialOpportunityError):
    """The opportunity is absent or outside the actor's ownership scope."""


class OpportunityVersionConflictError(CommercialOpportunityError):
    """The caller acted on an obsolete opportunity ownership epoch."""


class OpportunityIdempotencyConflictError(CommercialOpportunityError):
    """An idempotency key was reused for different opportunity meaning."""


class InvalidOpportunityCommandError(CommercialOpportunityError):
    """An opportunity command violates a domain invariant."""


_policy = CommercialCommandPolicy(
    validation_error=InvalidOpportunityCommandError,
    idempotency_error=OpportunityIdempotencyConflictError,
)


@dataclass(frozen=True, slots=True)
class OpportunityResult:
    opportunity: Opportunity
    created: bool


@dataclass(frozen=True, slots=True)
class OpportunityMutationResult:
    opportunity: Opportunity
    created: bool


@dataclass(frozen=True, slots=True)
class ConversationLinkResult:
    link: OpportunityConversation
    created: bool


class OpportunityService:
    """Own opportunity state and handoffs without changing chat route ownership."""

    async def create(
        self,
        db: AsyncSession,
        *,
        contact_id: uuid.UUID,
        source_conversation_id: uuid.UUID,
        created_by_agent_id: uuid.UUID,
        assigned_agent_id: uuid.UUID,
        assigned_operator_id: uuid.UUID | None,
        title: str,
        summary: str | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> OpportunityResult:
        normalized_title = _policy.required_text(title, "title", 200)
        normalized_summary = _policy.optional_text(summary, 8_000)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        await _assert_active_assignment(
            db,
            agent_id=assigned_agent_id,
            operator_id=assigned_operator_id,
        )
        contact = await _load_contact(db, contact_id)
        conversation = await db.get(ChatConversation, source_conversation_id)
        if (
            conversation is None
            or conversation.agent_id != created_by_agent_id
            or conversation.principal_id != contact.principal_id
        ):
            raise InvalidOpportunityCommandError(
                "source conversation does not prove contact access"
            )
        command_hash = _policy.command_hash(
            {
                "assigned_agent_id": str(assigned_agent_id),
                "assigned_operator_id": _uuid_text(assigned_operator_id),
                "contact_id": str(contact.id),
                "source_conversation_id": str(conversation.id),
                "summary": normalized_summary,
                "title": normalized_title,
            }
        )
        existing = (
            await db.execute(
                select(Opportunity).where(
                    Opportunity.created_by_agent_id == created_by_agent_id,
                    Opportunity.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            return OpportunityResult(opportunity=existing, created=False)

        opportunity_id = uuid.uuid5(
            created_by_agent_id,
            f"opportunity:{key}",
        )
        opportunity = Opportunity(
            id=opportunity_id,
            contact_id=contact.id,
            created_by_agent_id=created_by_agent_id,
            assigned_agent_id=assigned_agent_id,
            assigned_operator_id=assigned_operator_id,
            stage=OpportunityStage.NEW,
            control_version=0,
            title=normalized_title,
            summary=normalized_summary,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
        )
        db.add(opportunity)
        await db.flush()
        db.add_all(
            [
                OpportunityStageEvent(
                    id=uuid.uuid5(opportunity.id, "stage:0"),
                    opportunity_id=opportunity.id,
                    assigned_agent_id=assigned_agent_id,
                    actor_operator_id=assigned_operator_id,
                    event_type="created",
                    from_stage=None,
                    to_stage=OpportunityStage.NEW,
                    control_version=0,
                    correlation_id=correlation,
                    idempotency_key=key,
                    command_hash=_policy.command_hash(
                        {
                            "event_type": "created",
                            "opportunity_id": str(opportunity.id),
                            "to_stage": OpportunityStage.NEW,
                        }
                    ),
                ),
                OpportunityOwnershipEvent(
                    id=uuid.uuid5(opportunity.id, "ownership:0"),
                    opportunity_id=opportunity.id,
                    actor_agent_id=created_by_agent_id,
                    actor_operator_id=assigned_operator_id,
                    event_type="created",
                    from_agent_id=None,
                    to_agent_id=assigned_agent_id,
                    from_operator_id=None,
                    to_operator_id=assigned_operator_id,
                    control_version=0,
                    correlation_id=correlation,
                    idempotency_key=key,
                    command_hash=_policy.command_hash(
                        {
                            "event_type": "created",
                            "opportunity_id": str(opportunity.id),
                            "to_agent_id": str(assigned_agent_id),
                            "to_operator_id": _uuid_text(assigned_operator_id),
                        }
                    ),
                ),
                self._new_conversation_link(
                    opportunity=opportunity,
                    conversation=conversation,
                    actor_agent_id=created_by_agent_id,
                    actor_operator_id=assigned_operator_id,
                    correlation_id=correlation,
                    idempotency_key=key,
                ),
            ]
        )
        await db.flush()
        return OpportunityResult(opportunity=opportunity, created=True)

    async def transition_stage(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        target_stage: OpportunityStage | str,
        expected_version: int,
        reason: str | None,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> OpportunityMutationResult:
        target = _policy.enum_value(OpportunityStage, target_stage, "stage")
        normalized_reason = _policy.optional_text(reason, 8_000)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        event_time = _policy.aware_utc(occurred_at or datetime.now(UTC), "occurred_at")
        command_hash = _policy.command_hash(
            {
                "actor_agent_id": str(actor_agent_id),
                "actor_operator_id": _uuid_text(actor_operator_id),
                "expected_version": expected_version,
                "opportunity_id": str(opportunity_id),
                "reason": normalized_reason,
                "target_stage": target.value,
            }
        )
        opportunity = await self._load_for_update(db, opportunity_id)
        existing = (
            await db.execute(
                select(OpportunityStageEvent).where(
                    OpportunityStageEvent.opportunity_id == opportunity.id,
                    OpportunityStageEvent.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.assigned_agent_id != actor_agent_id:
                raise OpportunityNotFoundError("opportunity not found")
            _policy.assert_hash(existing.command_hash, command_hash)
            return OpportunityMutationResult(opportunity=opportunity, created=False)

        self._assert_owner(opportunity, actor_agent_id, actor_operator_id)
        self._assert_version(opportunity, expected_version)
        current = OpportunityStage(opportunity.stage)
        if current.value in _TERMINAL_STAGES:
            raise InvalidOpportunityCommandError(
                "a closed opportunity cannot change stage"
            )
        if target is OpportunityStage.NEW or target is current:
            raise InvalidOpportunityCommandError("invalid opportunity stage transition")

        opportunity.control_version += 1
        opportunity.stage = target.value
        if target.value in _TERMINAL_STAGES:
            opportunity.closed_at = event_time
        event = OpportunityStageEvent(
            id=uuid.uuid5(opportunity.id, f"stage:{opportunity.control_version}"),
            opportunity_id=opportunity.id,
            assigned_agent_id=opportunity.assigned_agent_id,
            actor_operator_id=actor_operator_id,
            event_type="stage_changed",
            from_stage=current.value,
            to_stage=target.value,
            control_version=opportunity.control_version,
            reason=normalized_reason,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
            created_at=event_time,
        )
        db.add(event)
        await db.flush()
        return OpportunityMutationResult(opportunity=opportunity, created=True)

    async def reassign(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        assigned_agent_id: uuid.UUID,
        assigned_operator_id: uuid.UUID | None,
        expected_version: int,
        reason: str | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> OpportunityMutationResult:
        normalized_reason = _policy.optional_text(reason, 8_000)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        await _assert_active_assignment(
            db,
            agent_id=assigned_agent_id,
            operator_id=assigned_operator_id,
        )
        command_hash = _policy.command_hash(
            {
                "actor_agent_id": str(actor_agent_id),
                "actor_operator_id": _uuid_text(actor_operator_id),
                "assigned_agent_id": str(assigned_agent_id),
                "assigned_operator_id": _uuid_text(assigned_operator_id),
                "expected_version": expected_version,
                "opportunity_id": str(opportunity_id),
                "reason": normalized_reason,
            }
        )
        opportunity = await self._load_for_update(db, opportunity_id)
        existing = (
            await db.execute(
                select(OpportunityOwnershipEvent).where(
                    OpportunityOwnershipEvent.opportunity_id == opportunity.id,
                    OpportunityOwnershipEvent.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.actor_agent_id != actor_agent_id:
                raise OpportunityNotFoundError("opportunity not found")
            _policy.assert_hash(existing.command_hash, command_hash)
            return OpportunityMutationResult(opportunity=opportunity, created=False)

        self._assert_owner(opportunity, actor_agent_id, actor_operator_id)
        self._assert_version(opportunity, expected_version)
        if (
            opportunity.assigned_agent_id == assigned_agent_id
            and opportunity.assigned_operator_id == assigned_operator_id
        ):
            raise InvalidOpportunityCommandError("opportunity assignment is unchanged")

        from_agent_id = opportunity.assigned_agent_id
        from_operator_id = opportunity.assigned_operator_id
        opportunity.control_version += 1
        ownership_event_id = uuid.uuid5(
            opportunity.id,
            f"ownership:{opportunity.control_version}",
        )
        event_time = datetime.now(UTC)
        active_follow_ups = list(
            (
                await db.execute(
                    select(FollowUpTask, ChatConversation)
                    .join(
                        ChatConversation,
                        ChatConversation.id == FollowUpTask.conversation_id,
                    )
                    .where(
                        FollowUpTask.opportunity_id == opportunity.id,
                        FollowUpTask.status.in_(_REASSIGNABLE_FOLLOW_UP_STATUSES),
                    )
                    .order_by(FollowUpTask.id)
                    .with_for_update(of=FollowUpTask)
                )
            ).all()
        )
        for task, conversation in active_follow_ups:
            from_status = task.status
            task.state_version += 1
            task.status = "review_required"
            task.review_required_at = event_time
            task.lease_owner = None
            task.lease_expires_at = None
            task.last_safe_code = _OPPORTUNITY_REASSIGNED
            follow_up_event_key = f"opportunity-reassigned:{ownership_event_id}"
            db.add(
                FollowUpTaskEvent(
                    id=uuid.uuid5(
                        task.id,
                        f"follow-up-event:{follow_up_event_key}",
                    ),
                    task_id=task.id,
                    opportunity_id=opportunity.id,
                    event_type="transitioned",
                    from_status=from_status,
                    to_status="review_required",
                    state_version=task.state_version,
                    actor_type=(
                        "operator" if actor_operator_id is not None else "agent"
                    ),
                    actor_agent_id=(
                        None if actor_operator_id is not None else actor_agent_id
                    ),
                    actor_admin_id=actor_operator_id,
                    actor_worker_id=None,
                    routing_agent_id=conversation.agent_id,
                    automation_agent_id=task.assigned_agent_id,
                    target_channel=task.target_channel,
                    control_version=task.scheduled_control_version,
                    automation_version=task.scheduled_automation_version,
                    scheduled_policy_version=task.scheduled_policy_version,
                    executed_policy_version=task.executed_policy_version,
                    consent_record_id=task.consent_record_id,
                    executed_consent_record_id=task.executed_consent_record_id,
                    caused_by_consent_record_id=None,
                    chat_message_id=task.chat_message_id,
                    outbound_message_id=task.outbound_message_id,
                    source_conversation_id=(
                        task.source_conversation_id or task.conversation_id
                    ),
                    had_chat_message_evidence=(
                        task.had_chat_message_evidence
                        or task.chat_message_id is not None
                    ),
                    had_outbound_message_evidence=(
                        task.had_outbound_message_evidence
                        or task.outbound_message_id is not None
                    ),
                    safe_code=_OPPORTUNITY_REASSIGNED,
                    correlation_id=correlation,
                    idempotency_key=follow_up_event_key,
                    command_hash=_policy.command_hash(
                        {
                            "from_status": from_status,
                            "opportunity_ownership_event_id": str(ownership_event_id),
                            "safe_code": _OPPORTUNITY_REASSIGNED,
                            "task_id": str(task.id),
                            "to_status": "review_required",
                        }
                    ),
                    created_at=event_time,
                )
            )

        opportunity.assigned_agent_id = assigned_agent_id
        opportunity.assigned_operator_id = assigned_operator_id

        event = OpportunityOwnershipEvent(
            id=ownership_event_id,
            opportunity_id=opportunity.id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            event_type="reassigned",
            from_agent_id=from_agent_id,
            to_agent_id=assigned_agent_id,
            from_operator_id=from_operator_id,
            to_operator_id=assigned_operator_id,
            control_version=opportunity.control_version,
            reason=normalized_reason,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
            created_at=event_time,
        )
        db.add(event)
        await db.flush()
        return OpportunityMutationResult(opportunity=opportunity, created=True)

    async def link_conversation(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        conversation_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> ConversationLinkResult:
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        opportunity = await self._load_for_update(db, opportunity_id)
        self._assert_owner(opportunity, actor_agent_id, actor_operator_id)
        existing = (
            await db.execute(
                select(OpportunityConversation).where(
                    OpportunityConversation.opportunity_id == opportunity.id,
                    OpportunityConversation.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        command_hash = _policy.command_hash(
            {
                "actor_agent_id": str(actor_agent_id),
                "actor_operator_id": _uuid_text(actor_operator_id),
                "conversation_id": str(conversation_id),
                "opportunity_id": str(opportunity.id),
            }
        )
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            return ConversationLinkResult(link=existing, created=False)

        conversation = await db.get(ChatConversation, conversation_id)
        contact = await _load_contact(db, opportunity.contact_id)
        if conversation is None or conversation.principal_id != contact.principal_id:
            raise InvalidOpportunityCommandError(
                "conversation does not belong to opportunity contact"
            )
        duplicate = (
            await db.execute(
                select(OpportunityConversation).where(
                    OpportunityConversation.opportunity_id == opportunity.id,
                    OpportunityConversation.conversation_id == conversation.id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise OpportunityIdempotencyConflictError(
                "conversation is already linked with another idempotency key"
            )
        link = self._new_conversation_link(
            opportunity=opportunity,
            conversation=conversation,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            correlation_id=correlation,
            idempotency_key=key,
        )
        db.add(link)
        await db.flush()
        return ConversationLinkResult(link=link, created=True)

    async def _load_for_update(
        self,
        db: AsyncSession,
        opportunity_id: uuid.UUID,
    ) -> Opportunity:
        opportunity = (
            await db.execute(
                select(Opportunity)
                .where(Opportunity.id == opportunity_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if opportunity is None:
            raise OpportunityNotFoundError("opportunity not found")
        return opportunity

    async def lock_owned(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
    ) -> Opportunity:
        """Lock one opportunity only when the caller owns its current epoch."""
        opportunity = await self._load_for_update(db, opportunity_id)
        self._assert_owner(opportunity, actor_agent_id, actor_operator_id)
        return opportunity

    @staticmethod
    def _assert_owner(
        opportunity: Opportunity,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
    ) -> None:
        if opportunity.assigned_agent_id != actor_agent_id:
            raise OpportunityNotFoundError("opportunity not found")
        if (
            opportunity.assigned_operator_id is not None
            and opportunity.assigned_operator_id != actor_operator_id
        ):
            raise OpportunityNotFoundError("opportunity not found")

    @staticmethod
    def _assert_version(opportunity: Opportunity, expected_version: int) -> None:
        if expected_version < 0 or opportunity.control_version != expected_version:
            raise OpportunityVersionConflictError("opportunity ownership epoch changed")

    @staticmethod
    def _new_conversation_link(
        *,
        opportunity: Opportunity,
        conversation: ChatConversation,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> OpportunityConversation:
        command_hash = _policy.command_hash(
            {
                "actor_agent_id": str(actor_agent_id),
                "actor_operator_id": _uuid_text(actor_operator_id),
                "conversation_id": str(conversation.id),
                "opportunity_id": str(opportunity.id),
            }
        )
        return OpportunityConversation(
            id=uuid.uuid5(opportunity.id, f"conversation:{conversation.id}"),
            opportunity_id=opportunity.id,
            conversation_id=conversation.id,
            linked_by_agent_id=actor_agent_id,
            linked_by_operator_id=actor_operator_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
        )


async def _load_contact(db: AsyncSession, contact_id: uuid.UUID) -> Contact:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.status == "archived":
        raise InvalidOpportunityCommandError("commercial contact is unavailable")
    return contact


async def _assert_active_assignment(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    operator_id: uuid.UUID | None,
) -> None:
    agent = await db.get(AgentProfile, agent_id)
    if agent is None or not agent.is_active:
        raise InvalidOpportunityCommandError("assigned agent is unavailable")
    if operator_id is not None:
        operator = await db.get(AdminUser, operator_id)
        if operator is None or not operator.is_active:
            raise InvalidOpportunityCommandError("assigned operator is unavailable")


def _uuid_text(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


opportunity_service = OpportunityService()
