"""Commercial opportunity ownership, history, links, and follow-up work."""

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

OPPORTUNITY_STAGES = (
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
)
_OPPORTUNITY_STAGE_SQL = ", ".join(f"'{stage}'" for stage in OPPORTUNITY_STAGES)
_SHA256_HEX_SQL = "'^[0-9a-f]{64}$'"


class Opportunity(TimestampedModel):
    """Commercial dossier whose assignment owns the sales workflow."""

    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint(
            f"stage IN ({_OPPORTUNITY_STAGE_SQL})",
            name="ck_opportunity_stage",
        ),
        CheckConstraint("control_version >= 0", name="ck_opportunity_control_version"),
        CheckConstraint(
            "char_length(btrim(title)) > 0",
            name="ck_opportunity_title",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_opportunity_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_idempotency",
        ),
        CheckConstraint(
            "(stage IN ('won', 'lost')) = (closed_at IS NOT NULL)",
            name="ck_opportunity_closed_at",
        ),
        UniqueConstraint(
            "created_by_agent_id",
            "idempotency_key",
            name="uq_opportunity_creator_idempotency",
        ),
        Index(
            "ix_opportunity_assignee_stage_updated",
            "assigned_agent_id",
            "stage",
            "updated_at",
        ),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage: Mapped[str] = mapped_column(
        String(30),
        default="new",
        server_default="new",
        nullable=False,
    )
    control_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OpportunityStageEvent(Base):
    """Append-only stage transition evidence for one opportunity epoch."""

    __tablename__ = "opportunity_stage_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'stage_changed')",
            name="ck_opportunity_stage_event_type",
        ),
        CheckConstraint(
            f"from_stage IS NULL OR from_stage IN ({_OPPORTUNITY_STAGE_SQL})",
            name="ck_opportunity_stage_event_from",
        ),
        CheckConstraint(
            f"to_stage IN ({_OPPORTUNITY_STAGE_SQL})",
            name="ck_opportunity_stage_event_to",
        ),
        CheckConstraint(
            "(event_type = 'created' AND control_version = 0 AND "
            "from_stage IS NULL AND to_stage = 'new') OR "
            "(event_type = 'stage_changed' AND control_version > 0 AND "
            "from_stage IS NOT NULL AND from_stage <> to_stage)",
            name="ck_opportunity_stage_event_shape",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_opportunity_stage_event_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_stage_event_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_stage_event_idempotency",
        ),
        UniqueConstraint(
            "opportunity_id",
            "control_version",
            name="uq_opportunity_stage_event_version",
        ),
        UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_stage_event_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class OpportunityOwnershipEvent(Base):
    """Append-only owner transition used to audit commercial handoffs."""

    __tablename__ = "opportunity_ownership_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'reassigned')",
            name="ck_opportunity_ownership_event_type",
        ),
        CheckConstraint(
            "(event_type = 'created' AND control_version = 0 AND "
            "from_agent_id IS NULL) OR "
            "(event_type = 'reassigned' AND control_version > 0 AND "
            "from_agent_id IS NOT NULL AND "
            "(from_agent_id <> to_agent_id OR "
            "from_operator_id IS DISTINCT FROM to_operator_id))",
            name="ck_opportunity_ownership_event_shape",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_opportunity_ownership_event_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_ownership_event_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_ownership_event_idempotency",
        ),
        UniqueConstraint(
            "opportunity_id",
            "control_version",
            name="uq_opportunity_ownership_event_version",
        ),
        UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_ownership_event_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    to_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class OpportunityConversation(Base):
    """Explicit source link that leaves conversation ownership unchanged."""

    __tablename__ = "opportunity_conversations"
    __table_args__ = (
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_opportunity_conversation_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_conversation_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_conversation_idempotency",
        ),
        UniqueConstraint(
            "opportunity_id",
            "conversation_id",
            name="uq_opportunity_conversation_link",
        ),
        UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_conversation_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
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
    linked_by_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    linked_by_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FollowUpTask(TimestampedModel):
    """Consent-gated commercial follow-up scheduled for one opportunity."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('commercial_follow_up', 'meeting_coordination', "
            "'proposal_reminder')",
            name="ck_follow_up_task_kind",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'in_progress', 'completed', 'cancelled', "
            "'review_required')",
            name="ck_follow_up_task_status",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_follow_up_task_state_version",
        ),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_follow_up_task_completed_at",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_follow_up_task_cancelled_at",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_follow_up_task_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_follow_up_task_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_follow_up_task_idempotency",
        ),
        UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_follow_up_task_idempotency",
        ),
        Index("ix_follow_up_task_due", "assigned_agent_id", "status", "due_at"),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_point_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_points.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    consent_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default="scheduled",
        server_default="scheduled",
        nullable=False,
    )
    state_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
