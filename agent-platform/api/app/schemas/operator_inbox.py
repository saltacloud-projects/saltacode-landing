"""Administration contracts for the agent-scoped operator inbox."""

from __future__ import annotations

from datetime import datetime
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


class InboxConversationOut(BaseModel):
    id: UUID
    principal_id: UUID
    display_name: str | None
    channel: str
    route_key: str
    status: str
    control_mode: ConversationControlMode
    control_version: int
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
