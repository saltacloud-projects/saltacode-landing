"""Privacy-minimized contracts for agent-scoped inbound review."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ChannelInboundStatusValue = Literal[
    "queued",
    "processing",
    "completed",
    "routed_to_human",
    "ignored",
    "review_required",
    "cancelled",
]


class ChannelInboundCommandRequest(BaseModel):
    expected_version: int = Field(ge=0)


class ChannelInboundSummaryOut(BaseModel):
    id: UUID
    channel: str
    adapter_key: str
    adapter_version: int
    channel_route_id: UUID
    channel_route_version: int
    channel_connection_id: UUID
    channel_connection_version: int
    status: ChannelInboundStatusValue
    phase: str
    state_version: int
    attempts: int
    safe_code: str | None
    conversation_id: UUID | None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None


class ChannelInboundDetailOut(ChannelInboundSummaryOut):
    routing_agent_id: UUID
    conversation_control_version: int | None
    automation_agent_id: UUID | None
    conversation_automation_version: int | None
    legacy_payload_quarantined: bool


class ChannelInboundEventOut(BaseModel):
    id: UUID
    event_type: str
    from_status: ChannelInboundStatusValue | Literal["failed"] | None
    to_status: ChannelInboundStatusValue
    state_version: int
    phase: str
    actor_type: Literal["system", "worker", "operator"]
    has_actor_admin: bool
    safe_code: str | None
    created_at: datetime


class ChannelInboundPageOut(BaseModel):
    items: list[ChannelInboundSummaryOut]
    total: int
    limit: int
    offset: int


class ChannelInboundTimelineOut(BaseModel):
    items: list[ChannelInboundEventOut]


class ChannelInboundMutationOut(BaseModel):
    id: UUID
    status: ChannelInboundStatusValue
    phase: str
    state_version: int
    safe_code: str | None
