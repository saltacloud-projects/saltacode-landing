"""Transactional meeting policy independent from calendar providers."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.meeting import Meeting, MeetingEvent, MeetingSlot
from app.models.opportunity import Opportunity, OpportunityConversation
from app.models.platform import ChatConversation
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.commercial._command_policy import CommercialCommandPolicy
from app.services.commercial.opportunities import (
    OpportunityStage,
    OpportunityVersionConflictError,
    opportunity_service,
)

_BLOCKED_SCHEDULE_STAGES = {
    OpportunityStage.PAUSED.value,
    OpportunityStage.WON.value,
    OpportunityStage.LOST.value,
}
_MAX_SLOT_DURATION = timedelta(days=1)


class MeetingStatus(StrEnum):
    REQUESTED = "requested"
    SLOTS_PROPOSED = "slots_proposed"
    AWAITING_RESPONSE = "awaiting_response"
    SLOT_SELECTED = "slot_selected"
    CALENDAR_PENDING = "calendar_pending"
    SCHEDULED = "scheduled"
    RESCHEDULE_REQUESTED = "reschedule_requested"
    CANCELLED = "cancelled"
    REVIEW_REQUIRED = "review_required"


class MeetingServiceError(Exception):
    """Base failure for meeting coordination policy."""


class MeetingNotFoundError(MeetingServiceError):
    """The meeting is absent from the current opportunity owner scope."""


class MeetingVersionConflictError(MeetingServiceError):
    """The caller acted on an obsolete meeting state."""


class MeetingIdempotencyConflictError(MeetingServiceError):
    """An idempotency key was reused for a different meeting command."""


class InvalidMeetingCommandError(MeetingServiceError):
    """The requested meeting mutation violates a domain invariant."""


_policy = CommercialCommandPolicy(
    validation_error=InvalidMeetingCommandError,
    idempotency_error=MeetingIdempotencyConflictError,
)


@dataclass(frozen=True, slots=True)
class MeetingActor:
    agent_id: uuid.UUID | None = None
    admin_id: uuid.UUID | None = None
    expected_opportunity_version: int | None = None
    expected_conversation_control_version: int | None = None
    expected_conversation_automation_version: int | None = None

    @property
    def actor_type(self) -> str:
        return "agent" if self.agent_id is not None else "operator"


@dataclass(frozen=True, slots=True)
class ProposedSlot:
    starts_at: datetime
    ends_at: datetime
    timezone: str


@dataclass(frozen=True, slots=True)
class MeetingMutationResult:
    meeting: Meeting
    opportunity: Opportunity
    created: bool


class MeetingService:
    """Own meeting state while deriving authorization from Opportunity."""

    async def create(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        actor: MeetingActor,
        correlation_id: str,
        idempotency_key: str,
    ) -> MeetingMutationResult:
        self._validate_actor_shape(actor)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        command_hash = _policy.command_hash(
            {
                "actor_admin_id": _uuid_text(actor.admin_id),
                "actor_agent_id": _uuid_text(actor.agent_id),
                "actor_expected_automation_version": (
                    actor.expected_conversation_automation_version
                ),
                "actor_expected_control_version": (
                    actor.expected_conversation_control_version
                ),
                "actor_expected_opportunity_version": (
                    actor.expected_opportunity_version
                ),
                "conversation_id": _uuid_text(conversation_id),
                "opportunity_id": str(opportunity_id),
            }
        )
        existing = (
            await db.execute(
                select(Meeting).where(
                    Meeting.created_under_agent_id == agent_id,
                    Meeting.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            opportunity = await self._lock_owned_opportunity(
                db,
                opportunity_id=existing.opportunity_id,
                agent_id=agent_id,
                actor=actor,
            )
            return MeetingMutationResult(
                meeting=existing,
                opportunity=opportunity,
                created=False,
            )

        opportunity = await self._lock_owned_opportunity(
            db,
            opportunity_id=opportunity_id,
            agent_id=agent_id,
            actor=actor,
        )
        self._assert_automation_opportunity_epoch(
            opportunity=opportunity,
            actor=actor,
        )
        conversation = await self._resolve_conversation(
            db,
            opportunity=opportunity,
            conversation_id=conversation_id,
            actor=actor,
        )
        meeting_id = uuid.uuid5(agent_id, f"meeting:{key}")
        meeting = Meeting(
            id=meeting_id,
            opportunity_id=opportunity.id,
            conversation_id=conversation.id if conversation else None,
            created_under_agent_id=agent_id,
            created_by_agent_id=actor.agent_id,
            created_by_admin_id=actor.admin_id,
            status=MeetingStatus.REQUESTED,
            state_version=0,
            proposal_version=0,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
        )
        db.add(meeting)
        await db.flush()
        db.add(
            self._event(
                meeting=meeting,
                opportunity=opportunity,
                conversation=conversation,
                actor=actor,
                event_type="created",
                from_status=None,
                to_status=MeetingStatus.REQUESTED,
                correlation_id=correlation,
                idempotency_key=key,
                command_hash=command_hash,
            )
        )
        await db.flush()
        return MeetingMutationResult(
            meeting=meeting,
            opportunity=opportunity,
            created=True,
        )

    async def propose_slots(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        meeting_id: uuid.UUID,
        actor: MeetingActor,
        expected_version: int,
        slots: list[ProposedSlot],
        reason: str | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> MeetingMutationResult:
        normalized_slots = [self._normalize_slot(slot) for slot in slots]
        if not 1 <= len(normalized_slots) <= 10:
            raise InvalidMeetingCommandError("meeting proposal requires 1 to 10 slots")
        context = await self._command_context(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=expected_version,
            command_payload={
                "reason": _policy.optional_text(reason, 1_000),
                "slots": [
                    {
                        "ends_at": slot.ends_at.isoformat(),
                        "starts_at": slot.starts_at.isoformat(),
                        "timezone": slot.timezone,
                    }
                    for slot in normalized_slots
                ],
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if context.replayed:
            return context.result
        if context.meeting.status not in {
            MeetingStatus.REQUESTED,
            MeetingStatus.SLOTS_PROPOSED,
            MeetingStatus.AWAITING_RESPONSE,
            MeetingStatus.RESCHEDULE_REQUESTED,
            MeetingStatus.REVIEW_REQUIRED,
        }:
            raise InvalidMeetingCommandError(
                "meeting cannot accept another slot proposal"
            )

        from_status = context.meeting.status
        context.meeting.state_version += 1
        context.meeting.proposal_version += 1
        context.meeting.status = MeetingStatus.SLOTS_PROPOSED
        context.meeting.selected_slot_id = None
        for position, slot in enumerate(normalized_slots, start=1):
            db.add(
                MeetingSlot(
                    id=uuid.uuid5(
                        context.meeting.id,
                        f"slot:{context.meeting.proposal_version}:{position}",
                    ),
                    meeting_id=context.meeting.id,
                    proposal_version=context.meeting.proposal_version,
                    position=position,
                    starts_at=slot.starts_at,
                    ends_at=slot.ends_at,
                    timezone=slot.timezone,
                )
            )
        db.add(
            self._event(
                meeting=context.meeting,
                opportunity=context.opportunity,
                conversation=context.conversation,
                actor=actor,
                event_type="slots_proposed",
                from_status=from_status,
                to_status=MeetingStatus.SLOTS_PROPOSED,
                reason=context.reason,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                command_hash=context.command_hash,
            )
        )
        await db.flush()
        return context.result

    async def mark_awaiting_response(
        self,
        db: AsyncSession,
        **kwargs,
    ) -> MeetingMutationResult:
        return await self._transition(
            db,
            target_status=MeetingStatus.AWAITING_RESPONSE,
            event_type="awaiting_response",
            allowed_from={MeetingStatus.SLOTS_PROPOSED},
            **kwargs,
        )

    async def select_slot(
        self,
        db: AsyncSession,
        *,
        slot_id: uuid.UUID,
        **kwargs,
    ) -> MeetingMutationResult:
        return await self._transition(
            db,
            target_status=MeetingStatus.SLOT_SELECTED,
            event_type="slot_selected",
            allowed_from={
                MeetingStatus.SLOTS_PROPOSED,
                MeetingStatus.AWAITING_RESPONSE,
            },
            slot_id=slot_id,
            **kwargs,
        )

    async def request_reschedule(
        self,
        db: AsyncSession,
        **kwargs,
    ) -> MeetingMutationResult:
        return await self._transition(
            db,
            target_status=MeetingStatus.RESCHEDULE_REQUESTED,
            event_type="reschedule_requested",
            allowed_from={MeetingStatus.SCHEDULED},
            **kwargs,
        )

    async def cancel(
        self,
        db: AsyncSession,
        **kwargs,
    ) -> MeetingMutationResult:
        return await self._transition(
            db,
            target_status=MeetingStatus.CANCELLED,
            event_type="cancelled",
            allowed_from=set(MeetingStatus)
            - {MeetingStatus.CANCELLED, MeetingStatus.CALENDAR_PENDING},
            **kwargs,
        )

    async def require_review(
        self,
        db: AsyncSession,
        **kwargs,
    ) -> MeetingMutationResult:
        return await self._transition(
            db,
            target_status=MeetingStatus.REVIEW_REQUIRED,
            event_type="review_required",
            allowed_from=set(MeetingStatus)
            - {
                MeetingStatus.CANCELLED,
                MeetingStatus.CALENDAR_PENDING,
                MeetingStatus.REVIEW_REQUIRED,
            },
            **kwargs,
        )

    async def schedule_manual(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        meeting_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        expected_opportunity_version: int,
        slot_id: uuid.UUID,
        evidence_type: str,
        evidence_reference: str,
        reason: str | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> MeetingMutationResult:
        actor = MeetingActor(admin_id=actor_admin_id)
        normalized_evidence_type = _policy.required_text(
            evidence_type,
            "evidence_type",
            40,
        )
        normalized_evidence_reference = _policy.required_text(
            evidence_reference,
            "evidence_reference",
            255,
        )
        context = await self._command_context(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=expected_version,
            command_payload={
                "evidence_reference": normalized_evidence_reference,
                "evidence_type": normalized_evidence_type,
                "expected_opportunity_version": expected_opportunity_version,
                "reason": _policy.optional_text(reason, 1_000),
                "slot_id": str(slot_id),
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if context.replayed:
            return context.result
        if context.opportunity.control_version != expected_opportunity_version:
            raise OpportunityVersionConflictError("opportunity ownership epoch changed")
        if context.opportunity.stage in _BLOCKED_SCHEDULE_STAGES:
            raise InvalidMeetingCommandError(
                "paused or closed opportunity cannot schedule a meeting"
            )
        if context.meeting.status not in {
            MeetingStatus.SLOTS_PROPOSED,
            MeetingStatus.AWAITING_RESPONSE,
            MeetingStatus.SLOT_SELECTED,
            MeetingStatus.RESCHEDULE_REQUESTED,
            MeetingStatus.REVIEW_REQUIRED,
        }:
            raise InvalidMeetingCommandError("meeting cannot be scheduled manually")
        slot = await self._current_slot(
            db,
            meeting=context.meeting,
            slot_id=slot_id,
        )

        from_status = context.meeting.status
        context.meeting.state_version += 1
        context.meeting.status = MeetingStatus.SCHEDULED
        context.meeting.selected_slot_id = slot.id
        if context.opportunity.stage != OpportunityStage.MEETING_SCHEDULED:
            await opportunity_service.transition_stage(
                db,
                opportunity_id=context.opportunity.id,
                actor_agent_id=context.opportunity.assigned_agent_id,
                actor_operator_id=actor_admin_id,
                target_stage=OpportunityStage.MEETING_SCHEDULED,
                expected_version=expected_opportunity_version,
                reason="Meeting confirmed with operator evidence.",
                correlation_id=context.correlation_id,
                idempotency_key=self._opportunity_stage_key(
                    meeting_id=context.meeting.id,
                    idempotency_key=context.idempotency_key,
                ),
            )
        db.add(
            self._event(
                meeting=context.meeting,
                opportunity=context.opportunity,
                conversation=context.conversation,
                actor=actor,
                event_type="scheduled_manual",
                from_status=from_status,
                to_status=MeetingStatus.SCHEDULED,
                slot_id=slot.id,
                evidence_type=normalized_evidence_type,
                evidence_reference=normalized_evidence_reference,
                reason=context.reason,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                command_hash=context.command_hash,
            )
        )
        await db.flush()
        return context.result

    async def _transition(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        meeting_id: uuid.UUID,
        actor: MeetingActor,
        expected_version: int,
        reason: str | None,
        correlation_id: str,
        idempotency_key: str,
        target_status: MeetingStatus,
        event_type: str,
        allowed_from: set[MeetingStatus],
        slot_id: uuid.UUID | None = None,
    ) -> MeetingMutationResult:
        context = await self._command_context(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor=actor,
            expected_version=expected_version,
            command_payload={
                "reason": _policy.optional_text(reason, 1_000),
                "slot_id": _uuid_text(slot_id),
                "target_status": target_status.value,
            },
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if context.replayed:
            return context.result
        current = MeetingStatus(context.meeting.status)
        if current not in allowed_from:
            raise InvalidMeetingCommandError(
                f"meeting cannot transition from {current.value} to "
                f"{target_status.value}"
            )
        slot = None
        if slot_id is not None:
            slot = await self._current_slot(
                db,
                meeting=context.meeting,
                slot_id=slot_id,
            )

        context.meeting.state_version += 1
        context.meeting.status = target_status
        if slot is not None:
            context.meeting.selected_slot_id = slot.id
        db.add(
            self._event(
                meeting=context.meeting,
                opportunity=context.opportunity,
                conversation=context.conversation,
                actor=actor,
                event_type=event_type,
                from_status=current,
                to_status=target_status,
                slot_id=slot.id if slot else None,
                reason=context.reason,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                command_hash=context.command_hash,
            )
        )
        await db.flush()
        return context.result

    async def _command_context(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        meeting_id: uuid.UUID,
        actor: MeetingActor,
        expected_version: int,
        command_payload: dict,
        correlation_id: str,
        idempotency_key: str,
    ) -> _MeetingCommandContext:
        self._validate_actor_shape(actor)
        correlation = _policy.required_text(correlation_id, "correlation_id", 120)
        key = _policy.required_text(idempotency_key, "idempotency_key", 220)
        reason = command_payload.get("reason")
        command_hash = _policy.command_hash(
            {
                "actor_admin_id": _uuid_text(actor.admin_id),
                "actor_agent_id": _uuid_text(actor.agent_id),
                "actor_expected_automation_version": (
                    actor.expected_conversation_automation_version
                ),
                "actor_expected_control_version": (
                    actor.expected_conversation_control_version
                ),
                "actor_expected_opportunity_version": (
                    actor.expected_opportunity_version
                ),
                "expected_version": expected_version,
                "meeting_id": str(meeting_id),
                **command_payload,
            }
        )
        meeting_snapshot = await db.get(Meeting, meeting_id)
        if meeting_snapshot is None:
            raise MeetingNotFoundError("meeting not found")
        opportunity = await self._lock_owned_opportunity(
            db,
            opportunity_id=meeting_snapshot.opportunity_id,
            agent_id=agent_id,
            actor=actor,
        )
        meeting = (
            await db.execute(
                select(Meeting).where(Meeting.id == meeting_id).with_for_update()
            )
        ).scalar_one_or_none()
        if meeting is None or meeting.opportunity_id != opportunity.id:
            raise MeetingNotFoundError("meeting not found")
        existing = (
            await db.execute(
                select(MeetingEvent).where(
                    MeetingEvent.meeting_id == meeting.id,
                    MeetingEvent.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        result = MeetingMutationResult(
            meeting=meeting,
            opportunity=opportunity,
            created=False,
        )
        if existing is not None:
            _policy.assert_hash(existing.command_hash, command_hash)
            return _MeetingCommandContext(
                meeting=meeting,
                opportunity=opportunity,
                conversation=None,
                correlation_id=correlation,
                idempotency_key=key,
                command_hash=command_hash,
                reason=reason,
                result=result,
                replayed=True,
            )
        self._assert_automation_opportunity_epoch(
            opportunity=opportunity,
            actor=actor,
        )
        conversation = await self._resolve_conversation(
            db,
            opportunity=opportunity,
            conversation_id=meeting.conversation_id,
            actor=actor,
            allow_absent=True,
        )
        if meeting.state_version != expected_version or expected_version < 0:
            raise MeetingVersionConflictError("meeting state version changed")
        return _MeetingCommandContext(
            meeting=meeting,
            opportunity=opportunity,
            conversation=conversation,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
            reason=reason,
            result=result,
            replayed=False,
        )

    async def _lock_owned_opportunity(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        agent_id: uuid.UUID,
        actor: MeetingActor,
    ) -> Opportunity:
        opportunity = (
            await db.execute(
                select(Opportunity)
                .where(Opportunity.id == opportunity_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if opportunity is None or opportunity.assigned_agent_id != agent_id:
            raise MeetingNotFoundError("meeting not found")
        await self._assert_actor_authorized(db, opportunity=opportunity, actor=actor)
        return opportunity

    async def _assert_actor_authorized(
        self,
        db: AsyncSession,
        *,
        opportunity: Opportunity,
        actor: MeetingActor,
    ) -> None:
        if actor.agent_id is not None:
            profile = await db.get(AgentProfile, actor.agent_id)
            if (
                profile is None
                or not profile.is_active
                or actor.agent_id != opportunity.assigned_agent_id
            ):
                raise MeetingNotFoundError("meeting not found")
            return

        admin = await db.get(AdminUser, actor.admin_id)
        if admin is None or not admin.is_active:
            raise InvalidMeetingCommandError("meeting operator is unavailable")
        if (
            opportunity.assigned_operator_id is not None
            and opportunity.assigned_operator_id != admin.id
        ):
            raise MeetingNotFoundError("meeting not found")
        if not await admin_agent_access_service.has_permission(
            db,
            admin_user_id=admin.id,
            role_key=admin.role,
            agent_id=opportunity.assigned_agent_id,
            permission=AdminPermission.MEETINGS_MANAGE,
        ):
            raise InvalidMeetingCommandError("meeting operator is not authorized")

    @staticmethod
    def _assert_automation_opportunity_epoch(
        *,
        opportunity: Opportunity,
        actor: MeetingActor,
    ) -> None:
        if (
            actor.agent_id is not None
            and actor.expected_opportunity_version != opportunity.control_version
        ):
            raise InvalidMeetingCommandError(
                "opportunity ownership epoch blocks automation"
            )

    async def _resolve_conversation(
        self,
        db: AsyncSession,
        *,
        opportunity: Opportunity,
        conversation_id: uuid.UUID | None,
        actor: MeetingActor,
        allow_absent: bool = False,
    ) -> ChatConversation | None:
        if conversation_id is None:
            if actor.agent_id is not None or not allow_absent:
                if actor.agent_id is not None:
                    raise InvalidMeetingCommandError(
                        "automation requires a linked conversation"
                    )
            return None
        conversation = (
            await db.execute(
                select(ChatConversation)
                .join(
                    OpportunityConversation,
                    OpportunityConversation.conversation_id == ChatConversation.id,
                )
                .where(
                    ChatConversation.id == conversation_id,
                    OpportunityConversation.opportunity_id == opportunity.id,
                )
                .with_for_update(of=ChatConversation)
            )
        ).scalar_one_or_none()
        if conversation is None:
            if allow_absent and actor.admin_id is not None:
                return None
            raise InvalidMeetingCommandError(
                "meeting conversation is unavailable or not linked"
            )
        if actor.agent_id is not None and (
            conversation.status != "active"
            or conversation.control_mode != "automated"
            or conversation.automation_agent_id != actor.agent_id
            or opportunity.assigned_agent_id != actor.agent_id
            or actor.expected_conversation_control_version
            != conversation.control_version
            or actor.expected_conversation_automation_version
            != conversation.automation_version
        ):
            raise InvalidMeetingCommandError(
                "conversation control or acting-agent epoch blocks automation"
            )
        return conversation

    async def _current_slot(
        self,
        db: AsyncSession,
        *,
        meeting: Meeting,
        slot_id: uuid.UUID,
    ) -> MeetingSlot:
        slot = await db.get(MeetingSlot, slot_id)
        if (
            slot is None
            or slot.meeting_id != meeting.id
            or slot.proposal_version != meeting.proposal_version
        ):
            raise InvalidMeetingCommandError(
                "selected slot does not belong to the current proposal"
            )
        return slot

    def _event(
        self,
        *,
        meeting: Meeting,
        opportunity: Opportunity,
        conversation: ChatConversation | None,
        actor: MeetingActor,
        event_type: str,
        from_status: MeetingStatus | str | None,
        to_status: MeetingStatus | str,
        correlation_id: str,
        idempotency_key: str,
        command_hash: str,
        slot_id: uuid.UUID | None = None,
        evidence_type: str | None = None,
        evidence_reference: str | None = None,
        reason: str | None = None,
        safe_code: str | None = None,
    ) -> MeetingEvent:
        return MeetingEvent(
            id=uuid.uuid5(meeting.id, f"event:{meeting.state_version}"),
            meeting_id=meeting.id,
            opportunity_id=opportunity.id,
            conversation_id=conversation.id if conversation else None,
            actor_type=actor.actor_type,
            actor_agent_id=actor.agent_id,
            actor_admin_id=actor.admin_id,
            assigned_agent_id=opportunity.assigned_agent_id,
            assigned_operator_id=opportunity.assigned_operator_id,
            routing_agent_id=conversation.agent_id if conversation else None,
            automation_agent_id=(
                conversation.automation_agent_id if conversation else None
            ),
            event_type=event_type,
            from_status=_enum_text(from_status),
            to_status=_enum_text(to_status),
            state_version=meeting.state_version,
            proposal_version=meeting.proposal_version,
            opportunity_control_version=opportunity.control_version,
            slot_id=slot_id,
            conversation_control_version=(
                conversation.control_version if conversation else None
            ),
            conversation_automation_version=(
                conversation.automation_version if conversation else None
            ),
            source_channel=conversation.channel if conversation else None,
            evidence_type=evidence_type,
            evidence_reference=evidence_reference,
            reason=reason,
            safe_code=safe_code,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _normalize_slot(slot: ProposedSlot) -> ProposedSlot:
        starts_at = _policy.aware_utc(slot.starts_at, "starts_at")
        ends_at = _policy.aware_utc(slot.ends_at, "ends_at")
        timezone = _policy.required_text(slot.timezone, "timezone", 64)
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise InvalidMeetingCommandError("invalid timezone") from exc
        if ends_at <= starts_at or ends_at - starts_at > _MAX_SLOT_DURATION:
            raise InvalidMeetingCommandError("invalid meeting slot range")
        return ProposedSlot(
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=timezone,
        )

    @staticmethod
    def _validate_actor_shape(actor: MeetingActor) -> None:
        if (actor.agent_id is None) == (actor.admin_id is None):
            raise InvalidMeetingCommandError(
                "meeting command requires exactly one actor"
            )
        expected_epochs = (
            actor.expected_opportunity_version,
            actor.expected_conversation_control_version,
            actor.expected_conversation_automation_version,
        )
        if actor.agent_id is not None and any(
            value is None for value in expected_epochs
        ):
            raise InvalidMeetingCommandError(
                "automation requires opportunity, control, and acting-agent epochs"
            )
        if actor.admin_id is not None and any(
            value is not None for value in expected_epochs
        ):
            raise InvalidMeetingCommandError(
                "operator commands cannot claim automation epochs"
            )

    @staticmethod
    def _opportunity_stage_key(
        *,
        meeting_id: uuid.UUID,
        idempotency_key: str,
    ) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
        return f"meeting-stage:{meeting_id}:{digest}"


@dataclass(frozen=True, slots=True)
class _MeetingCommandContext:
    meeting: Meeting
    opportunity: Opportunity
    conversation: ChatConversation | None
    correlation_id: str
    idempotency_key: str
    command_hash: str
    reason: str | None
    result: MeetingMutationResult
    replayed: bool


def _uuid_text(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _enum_text(value: StrEnum | str | None) -> str | None:
    if value is None:
        return None
    return value.value if isinstance(value, StrEnum) else value


meeting_service = MeetingService()
