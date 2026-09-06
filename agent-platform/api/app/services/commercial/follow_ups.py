"""Consent-gated scheduling policy for commercial follow-up work."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact, ContactPoint
from app.models.opportunity import FollowUpTask, Opportunity
from app.services.commercial._command_policy import CommercialCommandPolicy
from app.services.commercial.consents import ConsentPurpose, ConsentService
from app.services.commercial.opportunities import (
    CommercialOpportunityError,
    InvalidOpportunityCommandError,
    OpportunityIdempotencyConflictError,
    OpportunityService,
    OpportunityVersionConflictError,
)

_TERMINAL_STAGES = {"won", "lost"}


class FollowUpKind(StrEnum):
    COMMERCIAL_FOLLOW_UP = "commercial_follow_up"
    MEETING_COORDINATION = "meeting_coordination"
    PROPOSAL_REMINDER = "proposal_reminder"


class FollowUpStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REVIEW_REQUIRED = "review_required"


class InvalidFollowUpCommandError(InvalidOpportunityCommandError):
    """A follow-up command violates scheduling or lifecycle policy."""


class FollowUpVersionConflictError(OpportunityVersionConflictError):
    """The caller acted on an obsolete follow-up state."""


class FollowUpIdempotencyConflictError(OpportunityIdempotencyConflictError):
    """An idempotency key was reused for different follow-up meaning."""


class FollowUpConsentRequiredError(CommercialOpportunityError):
    """No current point-specific consent permits commercial follow-up."""


class FollowUpNotFoundError(CommercialOpportunityError):
    """The follow-up task is absent from the owned opportunity."""


@dataclass(frozen=True, slots=True)
class FollowUpResult:
    task: FollowUpTask
    created: bool


_policy = CommercialCommandPolicy(
    validation_error=InvalidFollowUpCommandError,
    idempotency_error=FollowUpIdempotencyConflictError,
)


class FollowUpService:
    """Schedule follow-up only with current point-specific consent evidence."""

    def __init__(
        self,
        *,
        consents: ConsentService | None = None,
        opportunities: OpportunityService | None = None,
    ) -> None:
        self._consents = consents or ConsentService()
        self._opportunities = opportunities or OpportunityService()

    async def schedule(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        contact_point_id: uuid.UUID,
        kind: FollowUpKind | str,
        due_at: datetime,
        note: str | None,
        correlation_id: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> FollowUpResult:
        normalized_kind = _policy.enum_value(
            FollowUpKind,
            kind,
            "follow-up kind",
        )
        normalized_due = _policy.aware_utc(due_at, "due_at")
        effective_at = _policy.aware_utc(now or datetime.now(UTC), "now")
        if normalized_due <= effective_at:
            raise InvalidFollowUpCommandError("follow-up due_at must be future")
        normalized_note = _policy.optional_text(note, 8_000)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        opportunity = await self._opportunities.lock_owned(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
        )
        _assert_opportunity_open(opportunity)
        command_hash = _policy.command_hash(
            {
                "contact_point_id": str(contact_point_id),
                "due_at": normalized_due.isoformat(),
                "kind": normalized_kind.value,
                "note": normalized_note,
                "opportunity_id": str(opportunity.id),
            }
        )
        existing = (
            await db.execute(
                select(FollowUpTask).where(
                    FollowUpTask.opportunity_id == opportunity.id,
                    FollowUpTask.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            return FollowUpResult(task=existing, created=False)

        contact = await _load_contact(db, opportunity.contact_id)
        point = await db.get(ContactPoint, contact_point_id)
        if (
            point is None
            or point.contact_id != contact.id
            or point.verification_status == "revoked"
        ):
            raise InvalidFollowUpCommandError("follow-up contact point is unavailable")
        effective = await self._consents.effective(
            db,
            agent_id=opportunity.created_by_agent_id,
            principal_id=contact.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            contact_point_id=point.id,
            at=effective_at,
        )
        if not effective.granted or effective.record is None:
            raise FollowUpConsentRequiredError(
                "commercial follow-up requires current explicit consent"
            )

        task = FollowUpTask(
            id=uuid.uuid5(opportunity.id, f"follow-up:{key}"),
            opportunity_id=opportunity.id,
            contact_point_id=point.id,
            consent_record_id=effective.record.id,
            assigned_agent_id=opportunity.assigned_agent_id,
            assigned_operator_id=opportunity.assigned_operator_id,
            kind=normalized_kind.value,
            status=FollowUpStatus.SCHEDULED,
            state_version=0,
            due_at=normalized_due,
            note=normalized_note,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
        )
        db.add(task)
        await db.flush()
        return FollowUpResult(task=task, created=True)

    async def transition(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        target_status: FollowUpStatus | str,
        expected_version: int,
        occurred_at: datetime | None = None,
    ) -> FollowUpTask:
        target = _policy.enum_value(
            FollowUpStatus,
            target_status,
            "follow-up status",
        )
        event_time = _policy.aware_utc(
            occurred_at or datetime.now(UTC),
            "occurred_at",
        )
        task = (
            await db.execute(
                select(FollowUpTask).where(FollowUpTask.id == task_id).with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise FollowUpNotFoundError("follow-up task not found")
        await self._opportunities.lock_owned(
            db,
            opportunity_id=task.opportunity_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
        )
        if expected_version < 0 or task.state_version != expected_version:
            raise FollowUpVersionConflictError("follow-up task version changed")
        current = FollowUpStatus(task.status)
        allowed = {
            FollowUpStatus.SCHEDULED: {
                FollowUpStatus.IN_PROGRESS,
                FollowUpStatus.CANCELLED,
                FollowUpStatus.REVIEW_REQUIRED,
            },
            FollowUpStatus.IN_PROGRESS: {
                FollowUpStatus.COMPLETED,
                FollowUpStatus.CANCELLED,
                FollowUpStatus.REVIEW_REQUIRED,
            },
            FollowUpStatus.REVIEW_REQUIRED: {
                FollowUpStatus.SCHEDULED,
                FollowUpStatus.CANCELLED,
            },
            FollowUpStatus.COMPLETED: set(),
            FollowUpStatus.CANCELLED: set(),
        }
        if target not in allowed[current]:
            raise InvalidFollowUpCommandError("invalid follow-up status transition")

        task.status = target.value
        task.state_version += 1
        task.completed_at = event_time if target is FollowUpStatus.COMPLETED else None
        task.cancelled_at = event_time if target is FollowUpStatus.CANCELLED else None
        await db.flush()
        return task


async def _load_contact(db: AsyncSession, contact_id: uuid.UUID) -> Contact:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.status == "archived":
        raise InvalidFollowUpCommandError("commercial contact is unavailable")
    return contact


def _assert_opportunity_open(opportunity: Opportunity) -> None:
    if opportunity.stage in _TERMINAL_STAGES:
        raise InvalidFollowUpCommandError("commercial opportunity is closed")


follow_up_service = FollowUpService()
