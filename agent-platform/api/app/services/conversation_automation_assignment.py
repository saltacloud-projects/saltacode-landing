"""Assign the agent profile that automates one routed conversation."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.opportunity import Opportunity, OpportunityConversation
from app.models.platform import ChatConversation


class ConversationAutomationAssignmentError(Exception):
    """Base failure for acting-agent assignment commands."""


class ConversationAutomationAssignmentNotFoundError(
    ConversationAutomationAssignmentError
):
    """The conversation is absent from the requested routing-agent scope."""


class ConversationAutomationAssignmentValidationError(
    ConversationAutomationAssignmentError
):
    """The command violates an automation-assignment invariant."""


class ConversationAutomationAssignmentClosedError(
    ConversationAutomationAssignmentValidationError
):
    """A terminal conversation cannot accept another automation assignment."""


class ConversationAutomationAssignmentInactiveAgentError(
    ConversationAutomationAssignmentValidationError
):
    """A routing or target agent is absent or inactive."""


class ConversationAutomationAssignmentConflictError(
    ConversationAutomationAssignmentError
):
    """The command conflicts with durable assignment state."""


class ConversationAutomationAssignmentVersionConflictError(
    ConversationAutomationAssignmentConflictError
):
    """The caller acted on an obsolete automation epoch."""

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            f"automation version conflict: expected {expected}, actual {actual}"
        )
        self.expected = expected
        self.actual = actual


class ConversationAutomationAssignmentIdempotencyError(
    ConversationAutomationAssignmentConflictError
):
    """An idempotency key was reused for a different assignment command."""


@dataclass(frozen=True, slots=True)
class ConversationAutomationAssignmentResult:
    event: ConversationAutomationAssignmentEvent
    duplicate: bool

    @property
    def applied(self) -> bool:
        """Report whether this invocation advanced the assignment epoch."""

        return self.event.applied and not self.duplicate


class ConversationAutomationAssignmentService:
    """Own acting-agent epochs without changing route or human ownership."""

    async def assign(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        routing_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
        expected_automation_version: int,
        actor_agent_id: uuid.UUID | None,
        actor_admin_id: uuid.UUID | None,
        trigger: str,
        opportunity_id: uuid.UUID | None,
        correlation_id: str,
        idempotency_key: str,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ConversationAutomationAssignmentResult:
        self._validate_actor(actor_agent_id, actor_admin_id)
        if expected_automation_version < 0:
            raise ConversationAutomationAssignmentValidationError(
                "expected_automation_version must be non-negative"
            )
        normalized_trigger = self._required_text(trigger, "trigger", 80)
        normalized_correlation = self._required_text(
            correlation_id,
            "correlation_id",
            120,
        )
        normalized_key = self._required_text(
            idempotency_key,
            "idempotency_key",
            220,
        )
        normalized_reason = self._optional_text(reason, 1_000)
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": self._uuid_text(actor_admin_id),
                "actor_agent_id": self._uuid_text(actor_agent_id),
                "conversation_id": str(conversation_id),
                "expected_automation_version": expected_automation_version,
                "opportunity_id": self._uuid_text(opportunity_id),
                "reason": normalized_reason,
                "routing_agent_id": str(routing_agent_id),
                "target_agent_id": str(target_agent_id),
                "trigger": normalized_trigger,
            }
        )

        receipt = await self._receipt_by_key(
            db,
            conversation_id=conversation_id,
            idempotency_key=normalized_key,
        )
        if receipt is not None:
            return self._replay(
                receipt,
                routing_agent_id=routing_agent_id,
                command_hash=command_hash,
            )

        conversation = await self._load_conversation_for_update(
            db,
            conversation_id=conversation_id,
            routing_agent_id=routing_agent_id,
        )
        receipt = await self._receipt_by_key(
            db,
            conversation_id=conversation_id,
            idempotency_key=normalized_key,
        )
        if receipt is not None:
            return self._replay(
                receipt,
                routing_agent_id=routing_agent_id,
                command_hash=command_hash,
            )

        self._assert_conversation_open(conversation)
        await self._assert_active_agents(
            db,
            routing_agent_id=routing_agent_id,
            target_agent_id=target_agent_id,
        )
        if opportunity_id is not None:
            await self._assert_opportunity_assignment(
                db,
                conversation_id=conversation.id,
                opportunity_id=opportunity_id,
                target_agent_id=target_agent_id,
            )
        self._assert_version(conversation, expected_automation_version)

        from_agent_id = conversation.automation_agent_id
        applied = from_agent_id != target_agent_id
        if applied:
            conversation.automation_agent_id = target_agent_id
            conversation.automation_version += 1

        event = ConversationAutomationAssignmentEvent(
            id=uuid.uuid5(
                conversation.id,
                f"automation-assignment:{normalized_key}",
            ),
            conversation_id=conversation.id,
            routing_agent_id=conversation.agent_id,
            from_automation_agent_id=from_agent_id,
            to_automation_agent_id=target_agent_id,
            automation_version=conversation.automation_version,
            applied=applied,
            trigger=normalized_trigger,
            opportunity_id=opportunity_id,
            actor_agent_id=actor_agent_id,
            actor_admin_id=actor_admin_id,
            correlation_id=normalized_correlation,
            idempotency_key=normalized_key,
            command_hash=command_hash,
            reason=normalized_reason,
            created_at=event_time,
        )
        db.add(event)
        await db.flush()
        return ConversationAutomationAssignmentResult(event=event, duplicate=False)

    async def _receipt_by_key(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        idempotency_key: str,
    ) -> ConversationAutomationAssignmentEvent | None:
        return (
            await db.execute(
                select(ConversationAutomationAssignmentEvent).where(
                    ConversationAutomationAssignmentEvent.conversation_id
                    == conversation_id,
                    ConversationAutomationAssignmentEvent.idempotency_key
                    == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def _load_conversation_for_update(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        routing_agent_id: uuid.UUID,
    ) -> ChatConversation:
        conversation = (
            await db.execute(
                select(ChatConversation)
                .where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.agent_id == routing_agent_id,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise ConversationAutomationAssignmentNotFoundError(
                "conversation not found"
            )
        return conversation

    async def _assert_active_agents(
        self,
        db: AsyncSession,
        *,
        routing_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
    ) -> None:
        expected_ids = {routing_agent_id, target_agent_id}
        active_ids = set(
            (
                await db.execute(
                    select(AgentProfile.id).where(
                        AgentProfile.id.in_(expected_ids),
                        AgentProfile.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if routing_agent_id not in active_ids:
            raise ConversationAutomationAssignmentInactiveAgentError(
                "routing agent is absent or inactive"
            )
        if target_agent_id not in active_ids:
            raise ConversationAutomationAssignmentInactiveAgentError(
                "target agent is absent or inactive"
            )

    async def _assert_opportunity_assignment(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        target_agent_id: uuid.UUID,
    ) -> None:
        linked_opportunity_id = (
            await db.execute(
                select(Opportunity.id)
                .join(
                    OpportunityConversation,
                    OpportunityConversation.opportunity_id == Opportunity.id,
                )
                .where(
                    Opportunity.id == opportunity_id,
                    Opportunity.assigned_agent_id == target_agent_id,
                    OpportunityConversation.conversation_id == conversation_id,
                )
            )
        ).scalar_one_or_none()
        if linked_opportunity_id is None:
            raise ConversationAutomationAssignmentValidationError(
                "opportunity is not linked to the conversation and target agent"
            )

    @staticmethod
    def _replay(
        receipt: ConversationAutomationAssignmentEvent,
        *,
        routing_agent_id: uuid.UUID,
        command_hash: str,
    ) -> ConversationAutomationAssignmentResult:
        if receipt.routing_agent_id != routing_agent_id:
            raise ConversationAutomationAssignmentNotFoundError(
                "conversation not found"
            )
        if not secrets.compare_digest(receipt.command_hash, command_hash):
            raise ConversationAutomationAssignmentIdempotencyError(
                "idempotency key belongs to another assignment command"
            )
        return ConversationAutomationAssignmentResult(event=receipt, duplicate=True)

    @staticmethod
    def _assert_conversation_open(conversation: ChatConversation) -> None:
        if conversation.status != "active" or conversation.control_mode == "closed":
            raise ConversationAutomationAssignmentClosedError(
                "closed conversation cannot change automation assignment"
            )

    @staticmethod
    def _assert_version(
        conversation: ChatConversation,
        expected_version: int,
    ) -> None:
        if conversation.automation_version != expected_version:
            raise ConversationAutomationAssignmentVersionConflictError(
                expected=expected_version,
                actual=conversation.automation_version,
            )

    @staticmethod
    def _validate_actor(
        actor_agent_id: uuid.UUID | None,
        actor_admin_id: uuid.UUID | None,
    ) -> None:
        if (actor_agent_id is None) == (actor_admin_id is None):
            raise ConversationAutomationAssignmentValidationError(
                "exactly one assignment actor is required"
            )

    @staticmethod
    def _required_text(value: str, field: str, max_length: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > max_length:
            raise ConversationAutomationAssignmentValidationError(f"invalid {field}")
        return normalized

    @staticmethod
    def _optional_text(value: str | None, max_length: int) -> str | None:
        normalized = value.strip() if value else None
        if normalized is not None and len(normalized) > max_length:
            raise ConversationAutomationAssignmentValidationError("invalid reason")
        return normalized or None

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConversationAutomationAssignmentValidationError(
                "occurred_at must be timezone-aware"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _command_hash(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _uuid_text(value: uuid.UUID | None) -> str | None:
        return str(value) if value is not None else None


conversation_automation_assignment_service = ConversationAutomationAssignmentService()
