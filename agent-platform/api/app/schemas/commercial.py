"""Administration contracts for agent-scoped commercial operations."""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

OpportunityStageValue = Literal[
    "new",
    "qualified",
    "proposal_requested",
    "proposal_preparing",
    "proposal_sent",
    "negotiation",
    "meeting_scheduled",
    "won",
    "lost",
    "paused",
]
FollowUpKindValue = Literal[
    "commercial_follow_up",
    "meeting_coordination",
    "proposal_reminder",
]
FollowUpStatusValue = Literal[
    "scheduled",
    "dispatch_queued",
    "in_progress",
    "completed",
    "cancelled",
    "review_required",
]
QuoteRequestStatusValue = Literal[
    "unavailable", "review_required", "issued", "cancelled"
]


class CommercialOperatorOut(BaseModel):
    id: UUID
    name: str
    email: str


class CommercialAgentOut(BaseModel):
    id: UUID
    name: str


class ContactPointOut(BaseModel):
    id: UUID
    kind: Literal["email", "phone"]
    masked_value: str
    verification_status: str
    commercial_follow_up_allowed: bool
    quote_delivery_allowed: bool


class CommercialContactOut(BaseModel):
    id: UUID
    principal_id: UUID
    display_name: str | None
    company_name: str | None
    job_title: str | None
    status: str
    contact_points: list[ContactPointOut] = Field(default_factory=list)


class OpportunitySummaryOut(BaseModel):
    id: UUID
    title: str
    summary: str | None
    stage: OpportunityStageValue
    control_version: int
    contact: CommercialContactOut
    assigned_agent: CommercialAgentOut
    assigned_operator: CommercialOperatorOut | None
    linked_conversation_count: int
    pending_follow_up_count: int
    latest_quote_status: QuoteRequestStatusValue | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class OpportunityPageOut(BaseModel):
    items: list[OpportunitySummaryOut]
    total: int
    limit: int
    offset: int


class OpportunityCandidateOut(BaseModel):
    contact: CommercialContactOut
    conversation_id: UUID
    channel: str
    route_key: str
    conversation_status: str
    conversation_updated_at: datetime


class ConversationCandidateOut(BaseModel):
    id: UUID
    agent_id: UUID
    channel: str
    route_key: str
    status: str
    updated_at: datetime


class OpportunityConversationOut(BaseModel):
    id: UUID
    conversation_id: UUID | None
    target_channel: str | None
    channel: str | None
    route_key: str | None
    status: str | None
    linked_at: datetime


class OpportunityStageEventOut(BaseModel):
    id: UUID
    event_type: str
    from_stage: OpportunityStageValue | None
    to_stage: OpportunityStageValue
    control_version: int
    reason: str | None
    created_at: datetime


class OpportunityOwnershipEventOut(BaseModel):
    id: UUID
    event_type: str
    from_agent_id: UUID | None
    to_agent_id: UUID
    from_operator_id: UUID | None
    to_operator_id: UUID | None
    control_version: int
    reason: str | None
    created_at: datetime


class FollowUpTaskOut(BaseModel):
    id: UUID
    opportunity_id: UUID
    conversation_id: UUID | None
    target_channel: str | None
    assigned_agent_id: UUID
    assigned_operator_id: UUID | None
    kind: FollowUpKindValue
    status: FollowUpStatusValue
    state_version: int
    scheduled_control_version: int | None
    scheduled_automation_version: int | None
    scheduled_policy_version: int | None
    executed_policy_version: int | None
    due_at: datetime
    available_at: datetime
    attempts: int
    max_attempts: int
    quote_version_id: UUID | None
    last_safe_code: str | None
    review_required_at: datetime | None
    has_consent_evidence: bool
    has_executed_consent_evidence: bool
    has_chat_message_evidence: bool
    has_outbound_message_evidence: bool
    created_at: datetime
    updated_at: datetime


class QuoteVersionOut(BaseModel):
    id: UUID
    version: int
    status: Literal["issued"]
    authority_name: str
    authority_version: str
    external_reference: str
    content_hash: str
    issued_at: datetime
    recorded_at: datetime


class QuoteRequestOut(BaseModel):
    id: UUID
    status: QuoteRequestStatusValue
    state_version: int
    requirements: dict
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[QuoteVersionOut] = Field(default_factory=list)


class OpportunityDetailOut(OpportunitySummaryOut):
    available_conversations: list[ConversationCandidateOut] = Field(
        default_factory=list
    )
    conversations: list[OpportunityConversationOut] = Field(default_factory=list)
    stage_events: list[OpportunityStageEventOut] = Field(default_factory=list)
    ownership_events: list[OpportunityOwnershipEventOut] = Field(default_factory=list)
    follow_ups: list[FollowUpTaskOut] = Field(default_factory=list)
    quote_requests: list[QuoteRequestOut] = Field(default_factory=list)


class OpportunityCreateRequest(BaseModel):
    contact_id: UUID
    source_conversation_id: UUID
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=8_000)
    assigned_operator_id: UUID | None = None


class OpportunityStageTransitionRequest(BaseModel):
    target_stage: OpportunityStageValue
    expected_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=8_000)


class OpportunityReassignmentRequest(BaseModel):
    assigned_agent_id: UUID
    assigned_operator_id: UUID | None = None
    expected_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=8_000)


class OpportunityConversationLinkRequest(BaseModel):
    conversation_id: UUID


class FollowUpCreateRequest(BaseModel):
    contact_point_id: UUID
    conversation_id: UUID | None = None
    target_channel: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_-]{0,39}$",
    )
    quote_version_id: UUID | None = None
    kind: FollowUpKindValue
    due_at: datetime
    note: str | None = Field(default=None, max_length=8_000)


class FollowUpTransitionRequest(BaseModel):
    target_status: FollowUpStatusValue
    expected_version: int = Field(ge=0)
    safe_code: str | None = Field(default=None, min_length=1, max_length=80)


class CommercialAutomationPolicyOut(BaseModel):
    agent_id: UUID
    is_enabled: bool
    allowed_kinds: list[FollowUpKindValue] = Field(default_factory=list)
    timezone: str
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    min_interval_seconds: int
    max_attempts: int
    max_daily_tasks: int
    max_pending_tasks: int
    version: int


class CommercialAutomationPolicyUpdateRequest(BaseModel):
    expected_version: int = Field(ge=0)
    is_enabled: bool
    allowed_kinds: list[FollowUpKindValue] = Field(default_factory=list)
    timezone: str = Field(min_length=1, max_length=64)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    min_interval_seconds: int = Field(ge=0, le=2_678_400)
    max_attempts: int = Field(ge=1, le=20)
    max_daily_tasks: int = Field(ge=1, le=10_000)
    max_pending_tasks: int = Field(ge=1, le=100_000)


class CommercialConsentRevocationRequest(BaseModel):
    source_conversation_id: UUID
    contact_point_id: UUID
    target_channel: Literal["email", "whatsapp"]
    policy_version: str = Field(min_length=1, max_length=80)


class CommercialConsentRevocationOut(BaseModel):
    consent_record_id: UUID
    created: bool


class QuoteRequestCreateRequest(BaseModel):
    requirements: dict = Field(default_factory=dict)
    status: Literal["unavailable", "review_required"] = "unavailable"
    failure_code: str = Field(
        default="quote_provider_unavailable", min_length=1, max_length=80
    )


class AuthoritativeQuoteVersionCreateRequest(BaseModel):
    expected_version: int = Field(ge=0)
    authority_name: str = Field(min_length=1, max_length=120)
    authority_version: str = Field(min_length=1, max_length=80)
    external_reference: str = Field(min_length=1, max_length=255)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime


class OpportunityMutationOut(BaseModel):
    id: UUID
    stage: OpportunityStageValue
    control_version: int
    assigned_agent_id: UUID
    assigned_operator_id: UUID | None
    created: bool


class ConversationLinkMutationOut(BaseModel):
    id: UUID
    conversation_id: UUID | None
    created: bool


class FollowUpMutationOut(BaseModel):
    id: UUID
    status: FollowUpStatusValue
    state_version: int
    created: bool


class QuoteRequestMutationOut(BaseModel):
    id: UUID
    status: QuoteRequestStatusValue
    state_version: int
    failure_code: str | None
    created: bool


class QuoteVersionMutationOut(BaseModel):
    quote_request_id: UUID
    quote_request_status: QuoteRequestStatusValue
    quote_request_state_version: int
    quote_version_id: UUID
    version: int
    created: bool
