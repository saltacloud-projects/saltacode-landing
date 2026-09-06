"""Privacy-minimized contracts for agent-scoped meeting coordination."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

MeetingStatusValue = Literal[
    "requested",
    "slots_proposed",
    "awaiting_response",
    "slot_selected",
    "calendar_pending",
    "scheduled",
    "reschedule_requested",
    "cancelled",
    "review_required",
]


class MeetingSlotProposal(BaseModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_range(self) -> MeetingSlotProposal:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("meeting slot timestamps must include a timezone")
        if self.ends_at <= self.starts_at:
            raise ValueError("meeting slot end must be after its start")
        return self


class MeetingCreateRequest(BaseModel):
    opportunity_id: UUID
    conversation_id: UUID | None = None


class MeetingSlotProposalRequest(BaseModel):
    expected_version: int = Field(ge=0)
    slots: list[MeetingSlotProposal] = Field(min_length=1, max_length=10)
    reason: str | None = Field(default=None, max_length=1_000)


class MeetingTransitionRequest(BaseModel):
    expected_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=1_000)


class MeetingSlotSelectionRequest(BaseModel):
    expected_version: int = Field(ge=0)
    slot_id: UUID
    reason: str | None = Field(default=None, max_length=1_000)


class MeetingManualScheduleRequest(BaseModel):
    expected_version: int = Field(ge=0)
    expected_opportunity_version: int = Field(ge=0)
    slot_id: UUID
    evidence_type: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_-]{0,39}$",
    )
    evidence_reference: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=1_000)


class MeetingSlotOut(BaseModel):
    id: UUID
    proposal_version: int
    position: int
    starts_at: datetime
    ends_at: datetime
    timezone: str
    created_at: datetime


class MeetingEventOut(BaseModel):
    id: UUID
    event_type: str
    from_status: MeetingStatusValue | None
    to_status: MeetingStatusValue
    state_version: int
    proposal_version: int
    opportunity_control_version: int
    slot_id: UUID | None
    actor_type: Literal["agent", "operator"]
    actor_agent_id: UUID | None
    actor_admin_id: UUID | None
    assigned_agent_id: UUID
    assigned_operator_id: UUID | None
    conversation_id: UUID | None
    routing_agent_id: UUID | None
    automation_agent_id: UUID | None
    conversation_control_version: int | None
    conversation_automation_version: int | None
    source_channel: str | None
    evidence_type: str | None
    evidence_recorded: bool
    safe_code: str | None
    created_at: datetime


class MeetingSummaryOut(BaseModel):
    id: UUID
    opportunity_id: UUID
    conversation_id: UUID | None
    status: MeetingStatusValue
    state_version: int
    proposal_version: int
    selected_slot_id: UUID | None
    selected_slot: MeetingSlotOut | None
    created_at: datetime
    updated_at: datetime


class MeetingDetailOut(MeetingSummaryOut):
    slots: list[MeetingSlotOut] = Field(default_factory=list)
    events: list[MeetingEventOut] = Field(default_factory=list)


class MeetingPageOut(BaseModel):
    items: list[MeetingSummaryOut]
    total: int
    limit: int
    offset: int


class MeetingMutationOut(BaseModel):
    id: UUID
    opportunity_id: UUID
    status: MeetingStatusValue
    state_version: int
    proposal_version: int
    selected_slot_id: UUID | None
    opportunity_stage: str
    opportunity_control_version: int
    created: bool
