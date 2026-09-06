"""Durable consent-gated scheduling and policy for commercial follow-ups."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity, OpportunityConversation
from app.models.platform import ChatConversation
from app.models.quote import QuoteRequest, QuoteVersion
from app.services.channel_catalog import (
    ChannelAdapterUnavailable,
    ChannelCatalogError,
    require_implemented_adapter,
)
from app.services.commercial._command_policy import CommercialCommandPolicy
from app.services.commercial.consent_scope import (
    ConsentScope,
    acquire_consent_scope_lock,
)
from app.services.commercial.consents import (
    ConsentAction,
    ConsentPurpose,
    ConsentResult,
    ConsentService,
)
from app.services.commercial.contact_crypto import ContactCryptoError, contact_crypto
from app.services.commercial.opportunities import (
    CommercialOpportunityError,
    InvalidOpportunityCommandError,
    OpportunityIdempotencyConflictError,
    OpportunityService,
    OpportunityVersionConflictError,
)

_TERMINAL_STAGES = {"won", "lost"}
_LEGACY_CONTEXT_UNKNOWN = "legacy_follow_up_context_unknown"
_CONSENT_REVOKED = "commercial_consent_revoked"
_CONSENT_DELIVERY_UNCERTAIN = "commercial_consent_revoked_delivery_uncertain"
_CONSENT_SCOPE_AMBIGUOUS = "commercial_consent_scope_ambiguous"


class FollowUpKind(StrEnum):
    COMMERCIAL_FOLLOW_UP = "commercial_follow_up"
    MEETING_COORDINATION = "meeting_coordination"
    PROPOSAL_REMINDER = "proposal_reminder"


class FollowUpStatus(StrEnum):
    SCHEDULED = "scheduled"
    DISPATCH_QUEUED = "dispatch_queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REVIEW_REQUIRED = "review_required"


class InvalidFollowUpCommandError(InvalidOpportunityCommandError):
    """A follow-up command violates scheduling or lifecycle policy."""


class FollowUpVersionConflictError(OpportunityVersionConflictError):
    """The caller acted on an obsolete follow-up or policy state."""


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


@dataclass(frozen=True, slots=True)
class FollowUpConsentRevocationResult:
    consent: ConsentResult
    cancelled_tasks: int
    review_required_tasks: int


@dataclass(frozen=True, slots=True)
class CommercialAutomationPolicyView:
    agent_id: uuid.UUID
    is_enabled: bool
    allowed_kinds: list[str]
    timezone: str
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    min_interval_seconds: int
    max_attempts: int
    max_daily_tasks: int
    max_pending_tasks: int
    version: int


_policy = CommercialCommandPolicy(
    validation_error=InvalidFollowUpCommandError,
    idempotency_error=FollowUpIdempotencyConflictError,
)


class FollowUpService:
    """Own durable task registration while leaving delivery to a later worker."""

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
        conversation_id: uuid.UUID | None = None,
        target_channel: str | None = None,
        quote_version_id: uuid.UUID | None = None,
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
                "conversation_id": str(conversation_id) if conversation_id else None,
                "due_at": normalized_due.isoformat(),
                "kind": normalized_kind.value,
                "note": normalized_note,
                "opportunity_id": str(opportunity.id),
                "quote_version_id": (
                    str(quote_version_id) if quote_version_id else None
                ),
                "target_channel": target_channel,
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

        conversation = await _resolve_conversation(
            db,
            opportunity=opportunity,
            conversation_id=conversation_id,
        )
        _assert_dispatchable_conversation(conversation, opportunity)
        normalized_target_channel = _target_channel(
            target_channel or conversation.channel
        )
        authoritative_quote = await _resolve_quote_version(
            db,
            opportunity_id=opportunity.id,
            kind=normalized_kind,
            quote_version_id=quote_version_id,
        )
        contact = await _load_contact(db, opportunity.contact_id)
        point = await _load_contact_point(
            db,
            contact=contact,
            contact_point_id=contact_point_id,
        )
        _assert_contact_point_matches_target(
            point,
            target_channel=normalized_target_channel,
        )
        effective = await self._consents.effective(
            db,
            agent_id=conversation.agent_id,
            principal_id=contact.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            contact_point_id=point.id,
            source_conversation_id=conversation.id,
            target_channel=normalized_target_channel,
            at=effective_at,
        )
        if not effective.granted or effective.record is None:
            raise FollowUpConsentRequiredError(
                "commercial follow-up requires current explicit consent"
            )
        automation_policy = await _ensure_policy(
            db,
            agent_id=opportunity.assigned_agent_id,
            for_update=True,
        )
        pending_tasks = (
            await db.execute(
                select(func.count(FollowUpTask.id)).where(
                    FollowUpTask.assigned_agent_id == opportunity.assigned_agent_id,
                    FollowUpTask.status.in_(
                        (
                            FollowUpStatus.SCHEDULED,
                            FollowUpStatus.DISPATCH_QUEUED,
                            FollowUpStatus.IN_PROGRESS,
                            FollowUpStatus.REVIEW_REQUIRED,
                        )
                    ),
                )
            )
        ).scalar_one()
        if pending_tasks >= automation_policy.max_pending_tasks:
            raise InvalidFollowUpCommandError(
                "commercial automation pending task limit reached"
            )

        task = FollowUpTask(
            id=uuid.uuid5(opportunity.id, f"follow-up:{key}"),
            opportunity_id=opportunity.id,
            conversation_id=conversation.id,
            source_conversation_id=conversation.id,
            fifo_key=f"conversation:{conversation.id}",
            target_channel=normalized_target_channel,
            contact_point_id=point.id,
            consent_record_id=effective.record.id,
            assigned_agent_id=opportunity.assigned_agent_id,
            assigned_operator_id=opportunity.assigned_operator_id,
            quote_version_id=(authoritative_quote.id if authoritative_quote else None),
            kind=normalized_kind.value,
            status=FollowUpStatus.SCHEDULED,
            state_version=0,
            scheduled_control_version=conversation.control_version,
            scheduled_automation_version=conversation.automation_version,
            scheduled_policy_version=automation_policy.version,
            due_at=normalized_due,
            available_at=normalized_due,
            attempts=0,
            max_attempts=automation_policy.max_attempts,
            note=normalized_note,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
        )
        event = _event(
            task=task,
            event_type="scheduled",
            from_status=None,
            to_status=FollowUpStatus.SCHEDULED,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            actor_worker_id=None,
            routing_agent_id=conversation.agent_id,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
        )
        db.add_all([task, event])
        await db.flush()
        return FollowUpResult(task=task, created=True)

    async def revoke_commercial_follow_up_consent(
        self,
        db: AsyncSession,
        *,
        routing_agent_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        source_conversation_id: uuid.UUID,
        contact_point_id: uuid.UUID,
        target_channel: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> FollowUpConsentRevocationResult:
        """Append one revocation and fail closed all pending scoped work."""

        event_time = _policy.aware_utc(
            occurred_at or datetime.now(UTC),
            "occurred_at",
        )
        normalized_target = _target_channel(target_channel)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        conversation = await db.get(ChatConversation, source_conversation_id)
        if conversation is None or conversation.agent_id != routing_agent_id:
            raise FollowUpNotFoundError("consent scope was not found")
        contact, point = await _principal_contact_point(
            db,
            principal_id=conversation.principal_id,
            contact_point_id=contact_point_id,
        )
        _assert_contact_point_matches_target(point, target_channel=normalized_target)
        current = await self._consents.effective(
            db,
            agent_id=routing_agent_id,
            principal_id=conversation.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            contact_point_id=point.id,
            source_conversation_id=conversation.id,
            target_channel=normalized_target,
            at=event_time,
        )
        if current.record is None:
            raise FollowUpNotFoundError("consent scope was not found")
        revocation = await self._consents.record(
            db,
            agent_id=routing_agent_id,
            principal_id=conversation.principal_id,
            contact_id=contact.id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.REVOKE,
            policy_version=policy_version,
            channel=current.record.channel,
            target_channel=normalized_target,
            locale=current.record.locale,
            source_conversation_id=conversation.id,
            source_channel_identity_id=current.record.source_channel_identity_id,
            actor_admin_id=actor_admin_id,
            correlation_id=correlation,
            idempotency_key=key,
            occurred_at=event_time,
        )
        cancelled, review_required = await self._quarantine_revoked_scope(
            db,
            routing_agent_id=routing_agent_id,
            principal_id=conversation.principal_id,
            source_conversation_id=conversation.id,
            contact_point_id=point.id,
            target_channel=normalized_target,
            actor_admin_id=actor_admin_id,
            revocation_record_id=revocation.record.id,
            correlation_id=correlation,
            occurred_at=event_time,
        )
        await db.flush()
        return FollowUpConsentRevocationResult(
            consent=revocation,
            cancelled_tasks=cancelled,
            review_required_tasks=review_required,
        )

    async def _quarantine_revoked_scope(
        self,
        db: AsyncSession,
        *,
        routing_agent_id: uuid.UUID,
        principal_id: uuid.UUID,
        source_conversation_id: uuid.UUID,
        contact_point_id: uuid.UUID,
        target_channel: str,
        actor_admin_id: uuid.UUID,
        revocation_record_id: uuid.UUID,
        correlation_id: str,
        occurred_at: datetime,
    ) -> tuple[int, int]:
        rows = (
            await db.execute(
                select(FollowUpTask, ConsentRecord)
                .join(
                    ConsentRecord,
                    ConsentRecord.id == FollowUpTask.consent_record_id,
                )
                .where(
                    ConsentRecord.agent_id == routing_agent_id,
                    ConsentRecord.principal_id == principal_id,
                    ConsentRecord.purpose == ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                    ConsentRecord.source_conversation_id == source_conversation_id,
                    ConsentRecord.contact_point_id == contact_point_id,
                    or_(
                        ConsentRecord.target_channel == target_channel,
                        ConsentRecord.target_channel.is_(None),
                    ),
                    FollowUpTask.status.in_(
                        (
                            FollowUpStatus.SCHEDULED,
                            FollowUpStatus.DISPATCH_QUEUED,
                            FollowUpStatus.IN_PROGRESS,
                        )
                    ),
                )
                .order_by(FollowUpTask.id)
                .with_for_update()
            )
        ).all()
        cancelled = 0
        review_required = 0
        for task, scheduled_consent in rows:
            from_status = FollowUpStatus(task.status)
            exact_scope = (
                task.conversation_id == source_conversation_id
                and task.contact_point_id == contact_point_id
                and task.target_channel == target_channel
                and scheduled_consent.target_channel == target_channel
            )
            if exact_scope and from_status is FollowUpStatus.SCHEDULED:
                to_status = FollowUpStatus.CANCELLED
                safe_code = _CONSENT_REVOKED
                task.cancelled_at = occurred_at
                cancelled += 1
            else:
                to_status = FollowUpStatus.REVIEW_REQUIRED
                safe_code = (
                    _CONSENT_DELIVERY_UNCERTAIN
                    if exact_scope
                    else _CONSENT_SCOPE_AMBIGUOUS
                )
                task.review_required_at = occurred_at
                review_required += 1
            task.status = to_status.value
            task.state_version += 1
            task.lease_owner = None
            task.lease_expires_at = None
            task.last_safe_code = safe_code
            event_key = f"consent-revocation:{revocation_record_id}:{task.id}"
            event = _event(
                task=task,
                event_type="transitioned",
                from_status=from_status,
                to_status=to_status,
                actor_agent_id=None,
                actor_operator_id=actor_admin_id,
                actor_worker_id=None,
                routing_agent_id=routing_agent_id,
                correlation_id=correlation_id,
                idempotency_key=event_key,
                command_hash=_policy.command_hash(
                    {
                        "revocation_record_id": str(revocation_record_id),
                        "safe_code": safe_code,
                        "task_id": str(task.id),
                        "to_status": to_status.value,
                    }
                ),
                safe_code=safe_code,
                caused_by_consent_record_id=revocation_record_id,
            )
            db.add(event)
        return cancelled, review_required

    async def transition(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        target_status: FollowUpStatus | str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str,
        safe_code: str | None = None,
        occurred_at: datetime | None = None,
        allowed_source_statuses: frozenset[FollowUpStatus] | None = None,
        require_delivery_readiness: bool = False,
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
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        normalized_safe_code = _policy.optional_text(safe_code, 80)
        command_hash = _policy.command_hash(
            {
                "expected_version": expected_version,
                "safe_code": normalized_safe_code,
                "target_status": target.value,
                "task_id": str(task_id),
            }
        )
        if target is FollowUpStatus.SCHEDULED:
            scope = await _consent_scope_for_task(db, task_id=task_id)
            if scope is None:
                raise InvalidFollowUpCommandError(
                    "legacy follow-up requires an explicit replacement task"
                )
            await acquire_consent_scope_lock(db, scope=scope)
        opportunity_id = (
            await db.execute(
                select(FollowUpTask.opportunity_id).where(FollowUpTask.id == task_id)
            )
        ).scalar_one_or_none()
        if opportunity_id is None:
            raise FollowUpNotFoundError("follow-up task not found")
        opportunity = await self._opportunities.lock_owned(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
        )
        task = (
            await db.execute(
                select(FollowUpTask).where(FollowUpTask.id == task_id).with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise FollowUpNotFoundError("follow-up task not found")
        existing = (
            await db.execute(
                select(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.task_id == task.id,
                    FollowUpTaskEvent.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            return task
        if expected_version < 0 or task.state_version != expected_version:
            raise FollowUpVersionConflictError("follow-up task version changed")

        current = FollowUpStatus(task.status)
        if (
            allowed_source_statuses is not None
            and current not in allowed_source_statuses
        ):
            raise InvalidFollowUpCommandError(
                "follow-up is not eligible for this operation"
            )
        allowed = {
            FollowUpStatus.SCHEDULED: {
                FollowUpStatus.CANCELLED,
                FollowUpStatus.REVIEW_REQUIRED,
            },
            FollowUpStatus.DISPATCH_QUEUED: {
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
        if target is FollowUpStatus.COMPLETED and (
            task.executed_consent_record_id is None
            or (task.chat_message_id is None and task.outbound_message_id is None)
        ):
            raise InvalidFollowUpCommandError(
                "completed follow-up requires consent and output evidence"
            )

        conversation = await _task_conversation(db, task)
        if target is FollowUpStatus.SCHEDULED:
            _assert_opportunity_open(opportunity)
            if conversation is None:
                raise InvalidFollowUpCommandError(
                    "legacy follow-up requires an explicit replacement task"
                )
            _assert_dispatchable_conversation(conversation, opportunity)
            contact = await _load_contact(db, opportunity.contact_id)
            point = await _load_contact_point(
                db,
                contact=contact,
                contact_point_id=task.contact_point_id,
            )
            _assert_contact_point_matches_target(
                point,
                target_channel=task.target_channel,
            )
            effective = await self._consents.effective(
                db,
                agent_id=conversation.agent_id,
                principal_id=contact.principal_id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                contact_point_id=point.id,
                source_conversation_id=conversation.id,
                target_channel=task.target_channel,
                at=event_time,
            )
            if not effective.granted or effective.record is None:
                raise FollowUpConsentRequiredError(
                    "commercial follow-up requires current explicit consent"
                )
            await _assert_task_quote_still_issued(db, task)
            task.consent_record_id = effective.record.id
            task.scheduled_control_version = conversation.control_version
            task.scheduled_automation_version = conversation.automation_version
            automation_policy = await _ensure_policy(
                db,
                agent_id=opportunity.assigned_agent_id,
            )
            if require_delivery_readiness:
                _assert_policy_allows_requeue(automation_policy, task)
                await _assert_delivery_route_available(
                    db,
                    task=task,
                    source_conversation=conversation,
                    principal_id=contact.principal_id,
                    point=point,
                    acting_agent_id=opportunity.assigned_agent_id,
                )
            task.assigned_agent_id = opportunity.assigned_agent_id
            task.assigned_operator_id = opportunity.assigned_operator_id
            task.scheduled_policy_version = automation_policy.version
            task.executed_policy_version = None
            task.available_at = max(task.due_at, event_time)
            task.review_required_at = None
            task.last_safe_code = None
        elif target is FollowUpStatus.REVIEW_REQUIRED:
            task.review_required_at = event_time
            task.last_safe_code = normalized_safe_code or "manual_review_required"
        elif target is FollowUpStatus.CANCELLED:
            task.cancelled_at = event_time
            if task.last_safe_code is None and conversation is None:
                task.last_safe_code = _LEGACY_CONTEXT_UNKNOWN
        elif target is FollowUpStatus.COMPLETED:
            task.completed_at = event_time

        task.lease_owner = None
        task.lease_expires_at = None
        task.status = target.value
        task.state_version += 1
        event = _event(
            task=task,
            event_type="transitioned",
            from_status=current,
            to_status=target,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            actor_worker_id=None,
            routing_agent_id=conversation.agent_id if conversation else None,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
            safe_code=task.last_safe_code,
        )
        db.add(event)
        await db.flush()
        return task

    async def cancel(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> FollowUpTask:
        """Cancel work that has not crossed the external-delivery boundary."""

        return await self.transition(
            db,
            task_id=task_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            target_status=FollowUpStatus.CANCELLED,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            allowed_source_statuses=frozenset(
                {FollowUpStatus.SCHEDULED, FollowUpStatus.REVIEW_REQUIRED}
            ),
        )

    async def requeue(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> FollowUpTask:
        """Return reviewed work to the durable queue after every fence is valid."""

        return await self.transition(
            db,
            task_id=task_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            target_status=FollowUpStatus.SCHEDULED,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            allowed_source_statuses=frozenset({FollowUpStatus.REVIEW_REQUIRED}),
            require_delivery_readiness=True,
        )

    async def resolve_review(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID,
        expected_version: int,
        resolution: str,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> FollowUpTask:
        """Resolve review work without exposing the internal state machine."""

        if resolution == "requeue":
            return await self.requeue(
                db,
                task_id=task_id,
                actor_agent_id=actor_agent_id,
                actor_operator_id=actor_operator_id,
                expected_version=expected_version,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                occurred_at=occurred_at,
            )
        if resolution != "cancel":
            raise InvalidFollowUpCommandError("unsupported review resolution")
        return await self.transition(
            db,
            task_id=task_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
            target_status=FollowUpStatus.CANCELLED,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            allowed_source_statuses=frozenset({FollowUpStatus.REVIEW_REQUIRED}),
        )

    async def defer_scheduled(
        self,
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
        worker_id: str,
        available_at: datetime,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str,
        safe_code: str,
        occurred_at: datetime | None = None,
    ) -> FollowUpTask:
        """Record a policy deferral without treating it as a delivery attempt."""

        event_time = _policy.aware_utc(
            occurred_at or datetime.now(UTC),
            "occurred_at",
        )
        normalized_available = _policy.aware_utc(available_at, "available_at")
        if normalized_available <= event_time:
            raise InvalidFollowUpCommandError(
                "deferred follow-up available_at must be future"
            )
        normalized_worker = _policy.required_text(worker_id, "worker_id", 120)
        normalized_safe_code = _policy.required_text(safe_code, "safe_code", 80)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        command_hash = _policy.command_hash(
            {
                "available_at": normalized_available.isoformat(),
                "expected_version": expected_version,
                "safe_code": normalized_safe_code,
                "task_id": str(task_id),
            }
        )
        task = (
            await db.execute(
                select(FollowUpTask).where(FollowUpTask.id == task_id).with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise FollowUpNotFoundError("follow-up task not found")
        existing = (
            await db.execute(
                select(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.task_id == task.id,
                    FollowUpTaskEvent.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            return task
        if expected_version < 0 or task.state_version != expected_version:
            raise FollowUpVersionConflictError("follow-up task version changed")
        if FollowUpStatus(task.status) is not FollowUpStatus.SCHEDULED:
            raise InvalidFollowUpCommandError(
                "only a scheduled follow-up can be deferred"
            )
        policy = await _ensure_policy(
            db,
            agent_id=task.assigned_agent_id,
            for_update=True,
        )
        conversation = await _task_conversation(db, task)
        if conversation is None:
            raise InvalidFollowUpCommandError("follow-up conversation is unavailable")

        attempts = task.attempts
        task.available_at = normalized_available
        task.executed_policy_version = policy.version
        task.last_safe_code = normalized_safe_code
        task.state_version += 1
        event = _event(
            task=task,
            event_type="deferred",
            from_status=FollowUpStatus.SCHEDULED,
            to_status=FollowUpStatus.SCHEDULED,
            actor_agent_id=None,
            actor_operator_id=None,
            actor_worker_id=normalized_worker,
            routing_agent_id=conversation.agent_id,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
            safe_code=normalized_safe_code,
        )
        db.add(event)
        await db.flush()
        if task.attempts != attempts:
            raise RuntimeError("follow-up deferral consumed a delivery attempt")
        return task

    async def get_policy(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
    ) -> CommercialAutomationPolicyView:
        stored = (
            await db.execute(
                select(CommercialAutomationPolicy).where(
                    CommercialAutomationPolicy.agent_id == agent_id
                )
            )
        ).scalar_one_or_none()
        return _policy_view(stored, agent_id=agent_id)

    async def configure_policy(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        is_enabled: bool,
        allowed_kinds: list[FollowUpKind | str],
        timezone: str,
        quiet_hours_start: time | None,
        quiet_hours_end: time | None,
        min_interval_seconds: int,
        max_attempts: int,
        max_daily_tasks: int,
        max_pending_tasks: int,
    ) -> CommercialAutomationPolicyView:
        if expected_version < 0:
            raise FollowUpVersionConflictError("automation policy version changed")
        normalized_kinds = sorted(
            {
                _policy.enum_value(FollowUpKind, kind, "follow-up kind").value
                for kind in allowed_kinds
            }
        )
        normalized_timezone = _policy.required_text(timezone, "timezone", 64)
        try:
            ZoneInfo(normalized_timezone)
        except ZoneInfoNotFoundError as exc:
            raise InvalidFollowUpCommandError("invalid timezone") from exc
        if (quiet_hours_start is None) != (quiet_hours_end is None):
            raise InvalidFollowUpCommandError(
                "quiet hours start and end must be configured together"
            )
        if quiet_hours_start is not None and quiet_hours_start == quiet_hours_end:
            raise InvalidFollowUpCommandError("quiet hours cannot cover zero time")
        if not 0 <= min_interval_seconds <= 2_678_400:
            raise InvalidFollowUpCommandError("invalid min_interval_seconds")
        if not 1 <= max_attempts <= 20:
            raise InvalidFollowUpCommandError("invalid max_attempts")
        if not 1 <= max_daily_tasks <= 10_000:
            raise InvalidFollowUpCommandError("invalid max_daily_tasks")
        if not 1 <= max_pending_tasks <= 100_000:
            raise InvalidFollowUpCommandError("invalid max_pending_tasks")

        stored = await _ensure_policy(db, agent_id=agent_id, for_update=True)
        if stored.version != expected_version:
            raise FollowUpVersionConflictError("automation policy version changed")
        stored.is_enabled = is_enabled
        stored.allowed_kinds = normalized_kinds
        stored.timezone = normalized_timezone
        stored.quiet_hours_start = quiet_hours_start
        stored.quiet_hours_end = quiet_hours_end
        stored.min_interval_seconds = min_interval_seconds
        stored.max_attempts = max_attempts
        stored.max_daily_tasks = max_daily_tasks
        stored.max_pending_tasks = max_pending_tasks
        stored.updated_by_admin_id = actor_admin_id
        stored.version += 1
        await db.flush()
        return _policy_view(stored, agent_id=agent_id)


async def _resolve_conversation(
    db: AsyncSession,
    *,
    opportunity: Opportunity,
    conversation_id: uuid.UUID | None,
) -> ChatConversation:
    linked_ids = list(
        (
            await db.execute(
                select(OpportunityConversation.conversation_id).where(
                    OpportunityConversation.opportunity_id == opportunity.id,
                    OpportunityConversation.conversation_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if conversation_id is None:
        if len(linked_ids) != 1:
            raise InvalidFollowUpCommandError(
                "follow-up requires exactly one linked conversation or an explicit one"
            )
        resolved_id = linked_ids[0]
    else:
        if conversation_id not in linked_ids:
            raise InvalidFollowUpCommandError(
                "follow-up conversation is not linked to the opportunity"
            )
        resolved_id = conversation_id
    conversation = (
        await db.execute(
            select(ChatConversation)
            .where(ChatConversation.id == resolved_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise InvalidFollowUpCommandError("follow-up conversation is unavailable")
    return conversation


async def _task_conversation(
    db: AsyncSession,
    task: FollowUpTask,
) -> ChatConversation | None:
    if task.conversation_id is None:
        return None
    return (
        await db.execute(
            select(ChatConversation)
            .where(ChatConversation.id == task.conversation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _consent_scope_for_task(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
) -> ConsentScope | None:
    row = (
        await db.execute(
            select(FollowUpTask, Opportunity, Contact, ChatConversation)
            .join(Opportunity, Opportunity.id == FollowUpTask.opportunity_id)
            .join(Contact, Contact.id == Opportunity.contact_id)
            .outerjoin(
                ChatConversation,
                ChatConversation.id == FollowUpTask.conversation_id,
            )
            .where(FollowUpTask.id == task_id)
        )
    ).one_or_none()
    if row is None:
        return None
    task, _opportunity, contact, conversation = row
    if (
        conversation is None
        or task.contact_point_id is None
        or task.target_channel is None
    ):
        return None
    return ConsentScope(
        routing_agent_id=conversation.agent_id,
        principal_id=contact.principal_id,
        purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
        source_conversation_id=conversation.id,
        target_channel=task.target_channel,
        contact_point_id=task.contact_point_id,
    )


def _assert_dispatchable_conversation(
    conversation: ChatConversation,
    opportunity: Opportunity,
) -> None:
    if conversation.status != "active" or conversation.control_mode != "automated":
        raise InvalidFollowUpCommandError(
            "scheduled follow-up requires an active automated conversation"
        )
    if conversation.automation_agent_id != opportunity.assigned_agent_id:
        raise InvalidFollowUpCommandError(
            "conversation acting agent must own the commercial opportunity"
        )


async def _resolve_quote_version(
    db: AsyncSession,
    *,
    opportunity_id: uuid.UUID,
    kind: FollowUpKind,
    quote_version_id: uuid.UUID | None,
) -> QuoteVersion | None:
    if kind is not FollowUpKind.PROPOSAL_REMINDER:
        if quote_version_id is not None:
            raise InvalidFollowUpCommandError(
                "quote_version_id is only valid for proposal reminders"
            )
        return None
    if quote_version_id is None:
        raise InvalidFollowUpCommandError(
            "proposal reminder requires an issued quote version"
        )
    version = (
        await db.execute(
            select(QuoteVersion)
            .join(QuoteRequest, QuoteRequest.id == QuoteVersion.quote_request_id)
            .where(
                QuoteVersion.id == quote_version_id,
                QuoteVersion.status == "issued",
                QuoteRequest.opportunity_id == opportunity_id,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise InvalidFollowUpCommandError(
            "proposal reminder requires an issued quote version"
        )
    return version


async def _assert_task_quote_still_issued(
    db: AsyncSession,
    task: FollowUpTask,
) -> None:
    if task.kind != FollowUpKind.PROPOSAL_REMINDER:
        return
    await _resolve_quote_version(
        db,
        opportunity_id=task.opportunity_id,
        kind=FollowUpKind.PROPOSAL_REMINDER,
        quote_version_id=task.quote_version_id,
    )


async def _load_contact(db: AsyncSession, contact_id: uuid.UUID) -> Contact:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.status == "archived":
        raise InvalidFollowUpCommandError("commercial contact is unavailable")
    return contact


async def _load_contact_point(
    db: AsyncSession,
    *,
    contact: Contact,
    contact_point_id: uuid.UUID | None,
) -> ContactPoint:
    if contact_point_id is None:
        raise InvalidFollowUpCommandError("follow-up contact point is unavailable")
    point = await db.get(ContactPoint, contact_point_id)
    if (
        point is None
        or point.contact_id != contact.id
        or point.verification_status != "verified"
    ):
        raise InvalidFollowUpCommandError("follow-up contact point is unavailable")
    return point


async def _principal_contact_point(
    db: AsyncSession,
    *,
    principal_id: uuid.UUID,
    contact_point_id: uuid.UUID,
) -> tuple[Contact, ContactPoint]:
    row = (
        await db.execute(
            select(Contact, ContactPoint)
            .join(ContactPoint, ContactPoint.contact_id == Contact.id)
            .where(
                Contact.principal_id == principal_id,
                ContactPoint.id == contact_point_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise FollowUpNotFoundError("consent scope was not found")
    return row


def _assert_contact_point_matches_target(
    point: ContactPoint,
    *,
    target_channel: str,
) -> None:
    expected_kind = {"email": "email", "whatsapp": "phone"}.get(target_channel)
    if expected_kind is None or point.kind != expected_kind:
        raise InvalidFollowUpCommandError(
            "follow-up contact point does not match target channel"
        )


async def _ensure_policy(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    for_update: bool = False,
) -> CommercialAutomationPolicy:
    policy_id = uuid.uuid5(agent_id, "commercial-automation-policy")
    await db.execute(
        postgresql_insert(CommercialAutomationPolicy)
        .values(id=policy_id, agent_id=agent_id)
        .on_conflict_do_nothing(index_elements=["agent_id"])
    )
    statement = select(CommercialAutomationPolicy).where(
        CommercialAutomationPolicy.agent_id == agent_id
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one()


def _policy_view(
    stored: CommercialAutomationPolicy | None,
    *,
    agent_id: uuid.UUID,
) -> CommercialAutomationPolicyView:
    if stored is None:
        return CommercialAutomationPolicyView(
            agent_id=agent_id,
            is_enabled=False,
            allowed_kinds=[],
            timezone="UTC",
            quiet_hours_start=None,
            quiet_hours_end=None,
            min_interval_seconds=3600,
            max_attempts=3,
            max_daily_tasks=25,
            max_pending_tasks=100,
            version=0,
        )
    return CommercialAutomationPolicyView(
        agent_id=stored.agent_id,
        is_enabled=stored.is_enabled,
        allowed_kinds=list(stored.allowed_kinds),
        timezone=stored.timezone,
        quiet_hours_start=stored.quiet_hours_start,
        quiet_hours_end=stored.quiet_hours_end,
        min_interval_seconds=stored.min_interval_seconds,
        max_attempts=stored.max_attempts,
        max_daily_tasks=stored.max_daily_tasks,
        max_pending_tasks=stored.max_pending_tasks,
        version=stored.version,
    )


def _event(
    *,
    task: FollowUpTask,
    event_type: str,
    from_status: FollowUpStatus | None,
    to_status: FollowUpStatus,
    actor_agent_id: uuid.UUID | None,
    actor_operator_id: uuid.UUID | None,
    actor_worker_id: str | None,
    routing_agent_id: uuid.UUID | None,
    correlation_id: str,
    idempotency_key: str,
    command_hash: str,
    safe_code: str | None = None,
    caused_by_consent_record_id: uuid.UUID | None = None,
) -> FollowUpTaskEvent:
    return FollowUpTaskEvent(
        id=uuid.uuid5(task.id, f"follow-up-event:{idempotency_key}"),
        task_id=task.id,
        opportunity_id=task.opportunity_id,
        event_type=event_type,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value,
        state_version=task.state_version,
        actor_type=(
            "worker"
            if actor_worker_id
            else "operator"
            if actor_operator_id
            else "agent"
        ),
        actor_agent_id=(
            None if actor_worker_id or actor_operator_id else actor_agent_id
        ),
        actor_admin_id=actor_operator_id,
        actor_worker_id=actor_worker_id,
        routing_agent_id=routing_agent_id,
        automation_agent_id=task.assigned_agent_id,
        target_channel=task.target_channel,
        control_version=task.scheduled_control_version,
        automation_version=task.scheduled_automation_version,
        scheduled_policy_version=task.scheduled_policy_version,
        executed_policy_version=task.executed_policy_version,
        consent_record_id=task.consent_record_id,
        executed_consent_record_id=task.executed_consent_record_id,
        caused_by_consent_record_id=caused_by_consent_record_id,
        chat_message_id=task.chat_message_id,
        outbound_message_id=task.outbound_message_id,
        source_conversation_id=(task.source_conversation_id or task.conversation_id),
        had_chat_message_evidence=(
            task.had_chat_message_evidence or task.chat_message_id is not None
        ),
        had_outbound_message_evidence=(
            task.had_outbound_message_evidence or task.outbound_message_id is not None
        ),
        safe_code=safe_code,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        command_hash=command_hash,
    )


def _assert_opportunity_open(opportunity: Opportunity) -> None:
    if opportunity.stage in _TERMINAL_STAGES:
        raise InvalidFollowUpCommandError("commercial opportunity is closed")


def _assert_policy_allows_requeue(
    policy: CommercialAutomationPolicy,
    task: FollowUpTask,
) -> None:
    if not policy.is_enabled or task.kind not in policy.allowed_kinds:
        raise InvalidFollowUpCommandError(
            "commercial automation policy does not allow this follow-up"
        )


async def _assert_delivery_route_available(
    db: AsyncSession,
    *,
    task: FollowUpTask,
    source_conversation: ChatConversation,
    principal_id: uuid.UUID,
    point: ContactPoint,
    acting_agent_id: uuid.UUID,
) -> None:
    if task.target_channel != "whatsapp":
        raise InvalidFollowUpCommandError("follow-up target channel is not implemented")
    try:
        target_digits = re.sub(r"\D", "", contact_crypto.decrypt(point.ciphertext))
    except ContactCryptoError as exc:
        raise InvalidFollowUpCommandError(
            "follow-up contact point is unavailable"
        ) from exc
    if not target_digits:
        raise InvalidFollowUpCommandError("follow-up contact point is unavailable")
    rows = (
        await db.execute(
            select(ChatConversation, ChannelAgentRoute, ChannelConnection)
            .join(
                ChannelAgentRoute,
                ChannelAgentRoute.id == ChatConversation.channel_route_id,
            )
            .join(
                ChannelConnection,
                ChannelConnection.id == ChannelAgentRoute.channel_connection_id,
            )
            .where(
                ChatConversation.agent_id == source_conversation.agent_id,
                ChatConversation.principal_id == principal_id,
                ChatConversation.channel == task.target_channel,
                ChatConversation.status == "active",
                ChatConversation.control_mode == "automated",
                ChatConversation.automation_agent_id == acting_agent_id,
                ChannelAgentRoute.agent_id == source_conversation.agent_id,
                ChannelAgentRoute.channel == task.target_channel,
                ChannelAgentRoute.is_active.is_(True),
                ChannelConnection.channel == task.target_channel,
                ChannelConnection.is_active.is_(True),
            )
            .with_for_update(of=ChatConversation)
        )
    ).all()
    matches = [
        (conversation, route, connection)
        for conversation, route, connection in rows
        if re.sub(r"\D", "", conversation.external_thread_id) == target_digits
    ]
    if len(matches) != 1:
        raise InvalidFollowUpCommandError("follow-up delivery route is unavailable")
    _conversation, route, connection = matches[0]
    try:
        require_implemented_adapter(
            channel=route.channel,
            adapter_key=connection.adapter_key,
        )
    except (ChannelAdapterUnavailable, ChannelCatalogError) as exc:
        raise InvalidFollowUpCommandError(
            "follow-up delivery route is unavailable"
        ) from exc


def _target_channel(value: str) -> str:
    normalized = _policy.required_text(value, "target_channel", 40).lower()
    if re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", normalized) is None:
        raise InvalidFollowUpCommandError("invalid target_channel")
    return normalized


follow_up_service = FollowUpService()
