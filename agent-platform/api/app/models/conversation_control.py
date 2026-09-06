"""Append-only audit events for conversation ownership and control."""

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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConversationControlEvent(Base):
    """Immutable record of one conversation ownership epoch."""

    __tablename__ = "conversation_control_events"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "control_version",
            name="uq_conversation_control_event_version",
        ),
        Index(
            "ix_conversation_control_event_conversation_created",
            "conversation_id",
            "created_at",
        ),
        CheckConstraint(
            "control_version > 0",
            name="ck_conversation_control_event_version",
        ),
        CheckConstraint(
            "event_type IN ('paused', 'taken_over', 'reassigned', 'resumed', 'closed')",
            name="ck_conversation_control_event_type",
        ),
        CheckConstraint(
            "from_mode IN ('automated', 'paused', 'human', 'closed')",
            name="ck_conversation_control_event_from_mode",
        ),
        CheckConstraint(
            "to_mode IN ('automated', 'paused', 'human', 'closed')",
            name="ck_conversation_control_event_to_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
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
    actor_admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    to_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    from_assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    to_assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
