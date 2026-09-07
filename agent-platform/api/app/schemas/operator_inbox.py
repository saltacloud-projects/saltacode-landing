"""Administration contracts for the agent-scoped operator inbox."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.chat_presence import InboxPresence
from app.schemas.conversation_control import (
    ConversationControlEventOut,
    ConversationControlMode,
)


class InboxMessageFilters(BaseModel):
    """Message-time range is half-open and independent of control activity."""

    last_message_from: AwareDatetime | None = None
    last_message_before: AwareDatetime | None = None
    unread_only: bool = False
    search: str | None = Field(default=None, max_length=120)

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_range(self) -> "InboxMessageFilters":
        if (
            self.last_message_from is not None
            and self.last_message_before is not None
            and self.last_message_from >= self.last_message_before
        ):
            raise ValueError("last_message_from must precede last_message_before")
        return self


class InboxOperatorOut(BaseModel):
    id: UUID
    name: str
    email: str


class InboxAgentOut(BaseModel):
    id: UUID
    name: str


class InboxAgentActivityOut(BaseModel):
    status: Literal["queued", "running"]
    agent_id: UUID
    name: str


class InboxReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_ids: list[UUID] = Field(min_length=1, max_length=1_000)


class InboxReadOut(BaseModel):
    unread_count: int


class InboxLiveSnapshotOut(BaseModel):
    revision: str
    presence_degraded: bool = False
    unread_conversations: int
    active_conversations: int
    historical_conversations: int


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
    last_message_at: datetime | None = None
    last_message_preview: str | None = Field(default=None, max_length=140)
    last_message_author_type: (
        Literal["visitor", "agent", "operator", "system", "unknown"] | None
    ) = None
    unread_count: int = 0
    latest_inbound_message_id: UUID | None = None
    agent_activity: InboxAgentActivityOut | None = None
    presence: InboxPresence = Field(default_factory=InboxPresence)


class InboxConversationPageOut(BaseModel):
    items: list[InboxConversationOut]
    total: int
    limit: int
    offset: int


class InboxMessageOut(BaseModel):
    author_type: Literal["visitor", "agent", "operator", "system", "unknown"] = (
        "unknown"
    )
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
