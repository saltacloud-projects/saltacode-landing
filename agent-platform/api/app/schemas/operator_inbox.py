"""Administration contracts for the agent-scoped operator inbox."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.conversation_control import (
    ConversationControlEventOut,
    ConversationControlMode,
)


class InboxOperatorOut(BaseModel):
    id: UUID
    name: str
    email: str


class InboxAgentOut(BaseModel):
    id: UUID
    name: str


class InboxConversationOut(BaseModel):
    id: UUID
    principal_id: UUID
    display_name: str | None
    channel: str
    route_key: str
    status: str
    control_mode: ConversationControlMode
    control_version: int
    routing_agent: InboxAgentOut
    automation_agent: InboxAgentOut
    automation_version: int
    assigned_operator: InboxOperatorOut | None
    control_changed_at: datetime
    control_reason: str | None
    message_count: int
    last_activity_at: datetime


class InboxConversationPageOut(BaseModel):
    items: list[InboxConversationOut]
    total: int
    limit: int
    offset: int


class InboxMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    status: str
    tool_names: list[str] = Field(default_factory=list)
    origin: str | None
    actor_admin_id: UUID | None
    created_at: datetime


class InboxThreadOut(BaseModel):
    conversation: InboxConversationOut
    messages: list[InboxMessageOut]
    control_events: list[ConversationControlEventOut]


AutomationAssignmentTrigger = Literal[
    "operator_assignment",
    "operator_reassignment",
]


class AutomationAssignmentRequest(BaseModel):
    target_agent_id: UUID
    expected_automation_version: int = Field(ge=0)
    trigger: AutomationAssignmentTrigger
    reason: str | None = Field(default=None, min_length=1, max_length=1_000)


class AutomationAssignmentReceiptOut(BaseModel):
    event_id: UUID
    applied: bool
    duplicate: bool
    automation_agent_id: UUID
    automation_version: int


class AutomationAssignmentEventOut(BaseModel):
    event_id: UUID
    from_automation_agent: InboxAgentOut
    to_automation_agent: InboxAgentOut
    automation_version: int
    applied: bool
    trigger: str
    actor_admin_id: UUID | None
    reason: str | None
    created_at: datetime


class AutomationAssignmentHistoryPageOut(BaseModel):
    items: list[AutomationAssignmentEventOut]
    total: int
    limit: int
    offset: int
