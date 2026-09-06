"""Contracts for auditable human control of one conversation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ConversationControlMode(StrEnum):
    AUTOMATED = "automated"
    PAUSED = "paused"
    HUMAN = "human"
    CLOSED = "closed"


class ConversationControlTransitionRequest(BaseModel):
    target_mode: ConversationControlMode
    expected_version: int = Field(ge=0)
    assigned_admin_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None


class OperatorMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=16_000)
    expected_version: int = Field(ge=0)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message content cannot be blank")
        return normalized


class ConversationControlSnapshotOut(BaseModel):
    conversation_id: UUID
    agent_id: UUID
    mode: ConversationControlMode
    version: int
    assigned_admin_id: UUID | None
    changed_at: datetime
    reason: str | None

    @classmethod
    def from_model(cls, conversation: Any) -> "ConversationControlSnapshotOut":
        return cls(
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            mode=conversation.control_mode,
            version=conversation.control_version,
            assigned_admin_id=conversation.assigned_admin_id,
            changed_at=conversation.control_changed_at,
            reason=conversation.control_reason,
        )


class ConversationControlEventOut(BaseModel):
    id: UUID
    conversation_id: UUID
    agent_id: UUID
    actor_admin_id: UUID
    event_type: str
    from_mode: ConversationControlMode
    to_mode: ConversationControlMode
    from_assigned_admin_id: UUID | None
    to_assigned_admin_id: UUID | None
    control_version: int
    reason: str | None
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, event: Any) -> "ConversationControlEventOut":
        return cls(
            id=event.id,
            conversation_id=event.conversation_id,
            agent_id=event.agent_id,
            actor_admin_id=event.actor_admin_id,
            event_type=event.event_type,
            from_mode=event.from_mode,
            to_mode=event.to_mode,
            from_assigned_admin_id=event.from_assigned_admin_id,
            to_assigned_admin_id=event.to_assigned_admin_id,
            control_version=event.control_version,
            reason=event.reason,
            metadata=dict(event.metadata_json or {}),
            created_at=event.created_at,
        )


class OperatorMessageOut(BaseModel):
    message_id: UUID
    delivery_status: str
    control: ConversationControlSnapshotOut
