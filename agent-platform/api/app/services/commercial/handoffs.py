"""Deterministic commercial handoff coordination."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_handoff_route import AgentHandoffRoute
from app.models.contact import Contact, ContactPoint
from app.models.opportunity import Opportunity, OpportunityConversation
from app.models.platform import ChatConversation
from app.services.agent_handoff_routes import AgentHandoffTrigger
from app.services.commercial._command_policy import CommercialCommandPolicy
from app.services.commercial.consents import (
    ConsentPurpose,
    ConsentService,
    ConsentServiceError,
)
from app.services.commercial.contacts import ContactServiceError
from app.services.commercial.opportunities import (
    InvalidOpportunityCommandError,
    OpportunityIdempotencyConflictError,
    OpportunityService,
)
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentService,
)

_policy = CommercialCommandPolicy(
    validation_error=InvalidOpportunityCommandError,
    idempotency_error=OpportunityIdempotencyConflictError,
)


class CommercialHandoffError(Exception):
    """Base failure for commercial handoff coordination."""


class CommercialHandoffRouteRequiredError(CommercialHandoffError):
    """No active deterministic route exists for the requested handoff."""


class CommercialHandoffContactEvidenceError(CommercialHandoffError):
    """Conversation, contact, or contact-point evidence is incomplete."""


class CommercialHandoffConsentRequiredError(CommercialHandoffError):
    """Current point-specific consent does not permit quote delivery."""


@dataclass(frozen=True, slots=True)
class CommercialHandoffResult:
    """Durable outcome of one quote-requested handoff command."""

    opportunity: Opportunity
    created: bool


class CommercialHandoffCoordinator:
    """Coordinate a quote-requested handoff within the caller's transaction."""

    def __init__(
        self,
        *,
        automation_assignments: ConversationAutomationAssignmentService | None = None,
        consents: ConsentService | None = None,
        opportunities: OpportunityService | None = None,
    ) -> None:
        self._automation_assignments = (
            automation_assignments or ConversationAutomationAssignmentService()
        )
        self._consents = consents or ConsentService()
        self._opportunities = opportunities or OpportunityService()

    async def quote_requested(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        contact_id: uuid.UUID,
        contact_point_id: uuid.UUID | None,
        title: str,
        summary: str | None,
        correlation_id: str,
        idempotency_key: str,
        at: datetime | None = None,
    ) -> CommercialHandoffResult:
        """Create an opportunity owned by the configured quote specialist."""
        normalized_title = _policy.required_text(title, "title", 200)
        normalized_summary = _policy.optional_text(summary, 8_000)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        existing = await self._load_existing(
            db,
            source_agent_id=source_agent_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            title=normalized_title,
            summary=normalized_summary,
            idempotency_key=key,
        )
        if existing is not None:
            return CommercialHandoffResult(opportunity=existing, created=False)

        if contact_point_id is None:
            raise CommercialHandoffContactEvidenceError(
                "quote handoff requires an explicit contact point"
            )

        route = await self._load_active_quote_route(
            db,
            source_agent_id=source_agent_id,
        )
        conversation = await db.get(ChatConversation, conversation_id)
        contact = await db.get(Contact, contact_id)
        point = await db.get(ContactPoint, contact_point_id)
        principal_id = self._validate_contact_evidence(
            source_agent_id=source_agent_id,
            conversation=conversation,
            contact=contact,
            point=point,
        )
        expected_automation_version = conversation.automation_version
        effective_at = self._aware_utc(at or datetime.now(UTC))
        try:
            effective = await self._consents.effective(
                db,
                agent_id=source_agent_id,
                principal_id=principal_id,
                purpose=ConsentPurpose.QUOTE_DELIVERY,
                contact_point_id=contact_point_id,
                at=effective_at,
            )
        except (ConsentServiceError, ContactServiceError) as exc:
            raise CommercialHandoffContactEvidenceError(
                "quote consent evidence does not match the contact"
            ) from exc
        if not effective.granted or effective.record is None:
            raise CommercialHandoffConsentRequiredError(
                "quote handoff requires current point-specific consent"
            )
        if effective.record.contact_id != contact_id:
            raise CommercialHandoffContactEvidenceError(
                "quote consent does not belong to the requested contact"
            )

        result = await self._opportunities.create(
            db,
            contact_id=contact_id,
            source_conversation_id=conversation_id,
            created_by_agent_id=source_agent_id,
            assigned_agent_id=route.target_agent_id,
            assigned_operator_id=None,
            title=normalized_title,
            summary=normalized_summary,
            correlation_id=correlation,
            idempotency_key=key,
        )
        await self._automation_assignments.assign(
            db,
            conversation_id=conversation_id,
            routing_agent_id=source_agent_id,
            target_agent_id=result.opportunity.assigned_agent_id,
            expected_automation_version=expected_automation_version,
            actor_agent_id=source_agent_id,
            actor_admin_id=None,
            trigger=AgentHandoffTrigger.QUOTE_REQUESTED,
            opportunity_id=result.opportunity.id,
            correlation_id=correlation,
            idempotency_key=self._assignment_idempotency_key(
                conversation_id=conversation_id,
                handoff_key=key,
            ),
            reason="quote requested commercial handoff",
        )
        return CommercialHandoffResult(
            opportunity=result.opportunity,
            created=result.created,
        )

    @staticmethod
    async def _load_existing(
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        contact_id: uuid.UUID,
        title: str,
        summary: str | None,
        idempotency_key: str,
    ) -> Opportunity | None:
        existing = (
            await db.execute(
                select(Opportunity)
                .where(
                    Opportunity.created_by_agent_id == source_agent_id,
                    Opportunity.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        link_exists = (
            await db.execute(
                select(OpportunityConversation.id).where(
                    OpportunityConversation.opportunity_id == existing.id,
                    OpportunityConversation.conversation_id == conversation_id,
                )
            )
        ).scalar_one_or_none()
        if (
            existing.contact_id != contact_id
            or existing.title != title
            or existing.summary != summary
            or link_exists is None
        ):
            raise OpportunityIdempotencyConflictError(
                "idempotency key was reused for different handoff meaning"
            )
        return existing

    @staticmethod
    async def _load_active_quote_route(
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
    ) -> AgentHandoffRoute:
        route = (
            await db.execute(
                select(AgentHandoffRoute)
                .where(
                    AgentHandoffRoute.source_agent_id == source_agent_id,
                    AgentHandoffRoute.trigger == AgentHandoffTrigger.QUOTE_REQUESTED,
                    AgentHandoffRoute.is_active.is_(True),
                )
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if route is None:
            raise CommercialHandoffRouteRequiredError(
                "active quote-requested handoff route not found"
            )
        return route

    @staticmethod
    def _validate_contact_evidence(
        *,
        source_agent_id: uuid.UUID,
        conversation: ChatConversation | None,
        contact: Contact | None,
        point: ContactPoint | None,
    ) -> uuid.UUID:
        if conversation is None or contact is None or point is None:
            raise CommercialHandoffContactEvidenceError(
                "quote handoff contact evidence was not found"
            )
        if (
            conversation.agent_id != source_agent_id
            or conversation.principal_id != contact.principal_id
            or point.contact_id != contact.id
            or point.verification_status == "revoked"
        ):
            raise CommercialHandoffContactEvidenceError(
                "quote handoff contact evidence is inconsistent"
            )
        return contact.principal_id

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise CommercialHandoffContactEvidenceError(
                "quote handoff timestamp must include a timezone"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _assignment_idempotency_key(
        *,
        conversation_id: uuid.UUID,
        handoff_key: str,
    ) -> str:
        receipt_id = uuid.uuid5(
            conversation_id,
            f"quote-requested:{handoff_key}",
        )
        return f"quote-requested:{receipt_id}"


commercial_handoff_coordinator = CommercialHandoffCoordinator()
