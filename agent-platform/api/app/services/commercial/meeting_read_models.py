"""Agent-scoped, privacy-minimized meeting projections for the panel."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.meeting import Meeting, MeetingEvent, MeetingSlot
from app.models.opportunity import Opportunity
from app.schemas.meeting import (
    MeetingDetailOut,
    MeetingEventOut,
    MeetingSlotOut,
    MeetingSummaryOut,
)


class MeetingReadNotFoundError(Exception):
    """A meeting or owning agent is absent from the requested scope."""


@dataclass(frozen=True, slots=True)
class MeetingPage:
    items: list[MeetingSummaryOut]
    total: int


class MeetingReadService:
    async def list_meetings(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        opportunity_id: uuid.UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> MeetingPage:
        await self._assert_agent_exists(db, agent_id)
        filters = [Opportunity.assigned_agent_id == agent_id]
        if opportunity_id is not None:
            filters.append(Meeting.opportunity_id == opportunity_id)
        if status is not None:
            filters.append(Meeting.status == status)
        total = int(
            (
                await db.execute(
                    select(func.count(Meeting.id))
                    .join(Opportunity, Opportunity.id == Meeting.opportunity_id)
                    .where(*filters)
                )
            ).scalar_one()
        )
        meeting_rows = list(
            (
                await db.execute(
                    select(Meeting, Opportunity.control_version)
                    .join(Opportunity, Opportunity.id == Meeting.opportunity_id)
                    .where(*filters)
                    .order_by(Meeting.updated_at.desc(), Meeting.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        meetings = [meeting for meeting, _ in meeting_rows]
        selected_slots = await self._selected_slots(db, meetings)
        return MeetingPage(
            items=[
                self._summary(
                    meeting,
                    opportunity_control_version,
                    selected_slots.get(meeting.selected_slot_id),
                )
                for meeting, opportunity_control_version in meeting_rows
            ],
            total=total,
        )

    async def get_meeting(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        meeting_id: uuid.UUID,
    ) -> MeetingDetailOut:
        meeting_row = (
            await db.execute(
                select(Meeting, Opportunity.control_version)
                .join(Opportunity, Opportunity.id == Meeting.opportunity_id)
                .where(
                    Meeting.id == meeting_id,
                    Opportunity.assigned_agent_id == agent_id,
                )
            )
        ).one_or_none()
        if meeting_row is None:
            raise MeetingReadNotFoundError("meeting not found")
        meeting, opportunity_control_version = meeting_row
        slots = list(
            (
                await db.execute(
                    select(MeetingSlot)
                    .where(MeetingSlot.meeting_id == meeting.id)
                    .order_by(
                        MeetingSlot.proposal_version,
                        MeetingSlot.position,
                    )
                )
            )
            .scalars()
            .all()
        )
        events = list(
            (
                await db.execute(
                    select(MeetingEvent)
                    .where(MeetingEvent.meeting_id == meeting.id)
                    .order_by(MeetingEvent.state_version)
                )
            )
            .scalars()
            .all()
        )
        slot_by_id = {slot.id: slot for slot in slots}
        return MeetingDetailOut(
            **self._summary(
                meeting,
                opportunity_control_version,
                slot_by_id.get(meeting.selected_slot_id),
            ).model_dump(),
            slots=[self._slot(slot) for slot in slots],
            events=[self._event(event) for event in events],
        )

    async def assert_owned(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        meeting_id: uuid.UUID,
    ) -> None:
        owned_id = (
            await db.execute(
                select(Meeting.id)
                .join(Opportunity, Opportunity.id == Meeting.opportunity_id)
                .where(
                    Meeting.id == meeting_id,
                    Opportunity.assigned_agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if owned_id is None:
            raise MeetingReadNotFoundError("meeting not found")

    async def _selected_slots(
        self,
        db: AsyncSession,
        meetings: list[Meeting],
    ) -> dict[uuid.UUID, MeetingSlot]:
        selected_ids = [
            meeting.selected_slot_id
            for meeting in meetings
            if meeting.selected_slot_id is not None
        ]
        if not selected_ids:
            return {}
        slots = list(
            (
                await db.execute(
                    select(MeetingSlot).where(MeetingSlot.id.in_(selected_ids))
                )
            )
            .scalars()
            .all()
        )
        return {slot.id: slot for slot in slots}

    @staticmethod
    def _summary(
        meeting: Meeting,
        opportunity_control_version: int,
        selected_slot: MeetingSlot | None,
    ) -> MeetingSummaryOut:
        return MeetingSummaryOut(
            id=meeting.id,
            opportunity_id=meeting.opportunity_id,
            opportunity_control_version=opportunity_control_version,
            conversation_id=meeting.conversation_id,
            status=meeting.status,
            state_version=meeting.state_version,
            proposal_version=meeting.proposal_version,
            selected_slot_id=meeting.selected_slot_id,
            selected_slot=(
                MeetingReadService._slot(selected_slot) if selected_slot else None
            ),
            created_at=meeting.created_at,
            updated_at=meeting.updated_at,
        )

    @staticmethod
    def _slot(slot: MeetingSlot) -> MeetingSlotOut:
        return MeetingSlotOut(
            id=slot.id,
            proposal_version=slot.proposal_version,
            position=slot.position,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
            timezone=slot.timezone,
            created_at=slot.created_at,
        )

    @staticmethod
    def _event(event: MeetingEvent) -> MeetingEventOut:
        return MeetingEventOut(
            id=event.id,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            state_version=event.state_version,
            proposal_version=event.proposal_version,
            opportunity_control_version=event.opportunity_control_version,
            slot_id=event.slot_id,
            actor_type=event.actor_type,
            actor_agent_id=event.actor_agent_id,
            actor_admin_id=event.actor_admin_id,
            assigned_agent_id=event.assigned_agent_id,
            assigned_operator_id=event.assigned_operator_id,
            conversation_id=event.conversation_id,
            routing_agent_id=event.routing_agent_id,
            automation_agent_id=event.automation_agent_id,
            conversation_control_version=event.conversation_control_version,
            conversation_automation_version=event.conversation_automation_version,
            source_channel=event.source_channel,
            evidence_type=event.evidence_type,
            evidence_recorded=event.evidence_reference is not None,
            safe_code=event.safe_code,
            created_at=event.created_at,
        )

    @staticmethod
    async def _assert_agent_exists(
        db: AsyncSession,
        agent_id: uuid.UUID,
    ) -> None:
        exists = (
            await db.execute(select(AgentProfile.id).where(AgentProfile.id == agent_id))
        ).scalar_one_or_none()
        if exists is None:
            raise MeetingReadNotFoundError("agent not found")


meeting_read_service = MeetingReadService()
