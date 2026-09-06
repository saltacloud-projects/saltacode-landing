"""Auditable meeting coordination without a calendar-provider dependency."""

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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel

MEETING_STATUSES = (
    "requested",
    "slots_proposed",
    "awaiting_response",
    "slot_selected",
    "calendar_pending",
    "scheduled",
    "reschedule_requested",
    "cancelled",
    "review_required",
)
MEETING_EVENT_TYPES = (
    "created",
    "slots_proposed",
    "awaiting_response",
    "slot_selected",
    "scheduled_manual",
    "reschedule_requested",
    "cancelled",
    "review_required",
)
_MEETING_STATUS_SQL = ", ".join(f"'{value}'" for value in MEETING_STATUSES)
_MEETING_EVENT_TYPE_SQL = ", ".join(f"'{value}'" for value in MEETING_EVENT_TYPES)
_SHA256_HEX_SQL = "'^[0-9a-f]{64}$'"


class Meeting(TimestampedModel):
    """Current meeting state; commercial ownership remains on Opportunity."""

    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_MEETING_STATUS_SQL})",
            name="ck_meeting_status",
        ),
        CheckConstraint("state_version >= 0", name="ck_meeting_state_version"),
        CheckConstraint(
            "proposal_version >= 0",
            name="ck_meeting_proposal_version",
        ),
        CheckConstraint(
            "((created_by_agent_id IS NOT NULL AND created_by_admin_id IS NULL) OR "
            "(created_by_agent_id IS NULL AND created_by_admin_id IS NOT NULL))",
            name="ck_meeting_creator",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_meeting_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_meeting_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_meeting_idempotency",
        ),
        UniqueConstraint(
            "created_under_agent_id",
            "idempotency_key",
            name="uq_meeting_agent_idempotency",
        ),
        Index(
            "ix_meeting_opportunity_status_updated",
            "opportunity_id",
            "status",
            "updated_at",
        ),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_under_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="requested",
        server_default="requested",
        nullable=False,
    )
    state_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    proposal_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    selected_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meeting_slots.id",
            name="fk_meeting_selected_slot",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class MeetingSlot(Base):
    """Immutable time option belonging to one numbered proposal."""

    __tablename__ = "meeting_slots"
    __table_args__ = (
        CheckConstraint("proposal_version > 0", name="ck_meeting_slot_proposal"),
        CheckConstraint("position > 0", name="ck_meeting_slot_position"),
        CheckConstraint("ends_at > starts_at", name="ck_meeting_slot_range"),
        CheckConstraint(
            "char_length(btrim(timezone)) > 0",
            name="ck_meeting_slot_timezone",
        ),
        UniqueConstraint(
            "meeting_id",
            "proposal_version",
            "position",
            name="uq_meeting_slot_proposal_position",
        ),
        Index(
            "ix_meeting_slot_meeting_proposal",
            "meeting_id",
            "proposal_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MeetingEvent(Base):
    """Append-only command receipt with ownership and conversation snapshots."""

    __tablename__ = "meeting_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_MEETING_EVENT_TYPE_SQL})",
            name="ck_meeting_event_type",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_MEETING_STATUS_SQL})",
            name="ck_meeting_event_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({_MEETING_STATUS_SQL})",
            name="ck_meeting_event_to_status",
        ),
        CheckConstraint(
            "(event_type = 'created' AND state_version = 0 AND "
            "from_status IS NULL AND to_status = 'requested') OR "
            "(event_type <> 'created' AND state_version > 0 AND "
            "from_status IS NOT NULL)",
            name="ck_meeting_event_shape",
        ),
        CheckConstraint(
            "proposal_version >= 0",
            name="ck_meeting_event_proposal_version",
        ),
        CheckConstraint(
            "opportunity_control_version >= 0",
            name="ck_meeting_event_opportunity_version",
        ),
        CheckConstraint(
            "actor_type IN ('agent', 'operator')",
            name="ck_meeting_event_actor_type",
        ),
        CheckConstraint(
            "((actor_type = 'agent' AND actor_agent_id IS NOT NULL "
            "AND actor_admin_id IS NULL) OR "
            "(actor_type = 'operator' AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NOT NULL))",
            name="ck_meeting_event_actor",
        ),
        CheckConstraint(
            "((routing_agent_id IS NULL AND automation_agent_id IS NULL "
            "AND conversation_control_version IS NULL "
            "AND conversation_automation_version IS NULL "
            "AND source_channel IS NULL) OR "
            "(routing_agent_id IS NOT NULL AND automation_agent_id IS NOT NULL "
            "AND conversation_control_version IS NOT NULL "
            "AND conversation_automation_version IS NOT NULL "
            "AND source_channel IS NOT NULL))",
            name="ck_meeting_event_conversation_snapshot",
        ),
        CheckConstraint(
            "conversation_control_version IS NULL OR conversation_control_version >= 0",
            name="ck_meeting_event_control_version",
        ),
        CheckConstraint(
            "conversation_automation_version IS NULL OR "
            "conversation_automation_version >= 0",
            name="ck_meeting_event_automation_version",
        ),
        CheckConstraint(
            "event_type <> 'scheduled_manual' OR "
            "(actor_type = 'operator' AND evidence_type IS NOT NULL "
            "AND evidence_reference IS NOT NULL AND slot_id IS NOT NULL)",
            name="ck_meeting_event_manual_evidence",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_meeting_event_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_meeting_event_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_meeting_event_idempotency",
        ),
        UniqueConstraint(
            "meeting_id",
            "state_version",
            name="uq_meeting_event_state_version",
        ),
        UniqueConstraint(
            "meeting_id",
            "idempotency_key",
            name="uq_meeting_event_idempotency",
        ),
        Index(
            "ix_meeting_event_opportunity_created",
            "opportunity_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    assigned_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    routing_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    automation_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    opportunity_control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_slots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    conversation_control_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    conversation_automation_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    source_channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
