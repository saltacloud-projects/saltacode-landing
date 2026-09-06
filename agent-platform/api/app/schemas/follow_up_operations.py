"""Privacy-minimized administration contracts for durable follow-ups."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.commercial import FollowUpKindValue, FollowUpStatusValue


class FollowUpQueueItemOut(BaseModel):
    id: UUID
    opportunity_id: UUID
    assigned_agent_id: UUID
    assigned_operator_id: UUID | None
    kind: FollowUpKindValue
    status: FollowUpStatusValue
    state_version: int
    due_at: datetime
    available_at: datetime
    attempts: int
    max_attempts: int
    is_leased: bool
    outbound_status: str | None
    safe_code: str | None
    review_required_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FollowUpQueuePageOut(BaseModel):
    items: list[FollowUpQueueItemOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class FollowUpDetailOut(FollowUpQueueItemOut):
    conversation_id: UUID | None
    has_retained_source_conversation: bool
    quote_version_id: UUID | None
    scheduled_control_version: int | None
    scheduled_automation_version: int | None
    scheduled_policy_version: int | None
    executed_policy_version: int | None
    has_consent_evidence: bool
    has_executed_consent_evidence: bool
    has_chat_message_evidence: bool
    has_outbound_message_evidence: bool
    completed_at: datetime | None
    cancelled_at: datetime | None


class FollowUpEventOut(BaseModel):
    id: UUID
    event_type: str
    from_status: FollowUpStatusValue | None
    to_status: FollowUpStatusValue
    state_version: int
    actor_type: str
    has_actor_agent: bool
    has_actor_admin: bool
    has_actor_worker: bool
    routing_agent_id: UUID | None
    automation_agent_id: UUID | None
    target_channel: str | None
    control_version: int | None
    automation_version: int | None
    scheduled_policy_version: int | None
    executed_policy_version: int | None
    has_consent_evidence: bool
    has_executed_consent_evidence: bool
    has_causal_consent_evidence: bool
    has_chat_message_evidence: bool
    has_outbound_message_evidence: bool
    safe_code: str | None
    created_at: datetime


class FollowUpEventPageOut(BaseModel):
    items: list[FollowUpEventOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class FollowUpCommandRequest(BaseModel):
    expected_version: int = Field(ge=0)


class FollowUpReviewResolutionRequest(FollowUpCommandRequest):
    resolution: Literal["requeue", "cancel"]


class FollowUpCommandOut(BaseModel):
    id: UUID
    status: FollowUpStatusValue
    state_version: int
