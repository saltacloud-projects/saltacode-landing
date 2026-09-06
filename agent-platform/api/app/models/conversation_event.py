"""Append-only events that make conversation state resumable."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConversationEvent(Base):
    """Immutable event ordered by a conversation-local monotonic sequence."""

    __tablename__ = "conversation_events"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_conversation_event_sequence"),
        CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_conversation_event_visibility",
        ),
        CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9]*(\\.[a-z0-9]+){1,5}$'",
            name="ck_conversation_event_type",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_conversation_event_payload_object",
        ),
        Index(
            "uq_conversation_event_sequence",
            "conversation_id",
            "sequence",
            unique=True,
        ),
        Index(
            "ix_conversation_event_agent_created",
            "agent_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    visibility: Mapped[str] = mapped_column(String(12), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
