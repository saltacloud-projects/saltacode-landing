"""Append-only audit evidence for conversation automation assignments."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_SHA256_HEX_SQL = "'^[0-9a-f]{64}$'"


class ConversationAutomationAssignmentEvent(Base):
    """Immutable receipt for one acting-agent assignment command."""

    __tablename__ = "conversation_automation_assignment_events"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_conversation_automation_assignment_idempotency",
        ),
        Index(
            "uq_conversation_automation_assignment_applied_version",
            "conversation_id",
            "automation_version",
            unique=True,
            postgresql_where=text("applied"),
        ),
        Index(
            "ix_conversation_automation_assignment_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index(
            "ix_conversation_automation_event_target_agent",
            "to_automation_agent_id",
        ),
        CheckConstraint(
            "automation_version >= 0",
            name="ck_conversation_automation_assignment_version",
        ),
        CheckConstraint(
            "((applied AND from_automation_agent_id <> to_automation_agent_id "
            "AND automation_version > 0) OR "
            "(NOT applied AND "
            "from_automation_agent_id = to_automation_agent_id))",
            name="ck_conversation_automation_assignment_shape",
        ),
        CheckConstraint(
            "((actor_agent_id IS NOT NULL AND actor_admin_id IS NULL) OR "
            "(actor_agent_id IS NULL AND actor_admin_id IS NOT NULL))",
            name="ck_conversation_automation_assignment_actor",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_conversation_automation_assignment_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(trigger)) > 0",
            name="ck_conversation_automation_assignment_trigger",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_conversation_automation_assignment_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_conversation_automation_assignment_idempotency",
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
    routing_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_automation_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_automation_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    automation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trigger: Mapped[str] = mapped_column(String(80), nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
