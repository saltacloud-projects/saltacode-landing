"""Durable commercial follow-up tasks and append-only lifecycle evidence."""

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

_FOLLOW_UP_KIND_SQL = (
    "'commercial_follow_up', 'meeting_coordination', 'proposal_reminder'"
)
_FOLLOW_UP_STATUS_SQL = (
    "'scheduled', 'dispatch_queued', 'in_progress', 'completed', 'cancelled', "
    "'review_required'"
)
_SHA256_HEX_SQL = "'^[0-9a-f]{64}$'"


class FollowUpTask(TimestampedModel):
    """Mutable queue projection for one consent-gated commercial action."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ({_FOLLOW_UP_KIND_SQL})",
            name="ck_follow_up_task_kind",
        ),
        CheckConstraint(
            f"status IN ({_FOLLOW_UP_STATUS_SQL})",
            name="ck_follow_up_task_status",
        ),
        CheckConstraint(
            "state_version >= 0 AND attempts >= 0 AND max_attempts > 0 "
            "AND attempts <= max_attempts",
            name="ck_follow_up_task_counters",
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
            "(status = 'review_required') = (review_required_at IS NOT NULL)",
            name="ck_follow_up_task_review_required_at",
        ),
        CheckConstraint(
            "status != 'review_required' OR char_length(btrim(last_safe_code)) > 0",
            name="ck_follow_up_task_review_safe_code",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_follow_up_task_lease_pair",
        ),
        CheckConstraint(
            "(status = 'in_progress') = "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_follow_up_task_in_progress_lease",
        ),
        CheckConstraint(
            "status NOT IN ('scheduled', 'dispatch_queued', 'in_progress') OR "
            "(conversation_id IS NOT NULL AND char_length(btrim(fifo_key)) > 0 "
            "AND char_length(btrim(target_channel)) > 0 "
            "AND scheduled_control_version IS NOT NULL "
            "AND scheduled_automation_version IS NOT NULL "
            "AND scheduled_policy_version IS NOT NULL)",
            name="ck_follow_up_task_dispatch_snapshot",
        ),
        CheckConstraint(
            "scheduled_control_version IS NULL OR scheduled_control_version >= 0",
            name="ck_follow_up_task_control_version",
        ),
        CheckConstraint(
            "scheduled_automation_version IS NULL OR scheduled_automation_version >= 0",
            name="ck_follow_up_task_automation_version",
        ),
        CheckConstraint(
            "scheduled_policy_version IS NULL OR scheduled_policy_version >= 0",
            name="ck_follow_up_task_scheduled_policy_version",
        ),
        CheckConstraint(
            "executed_policy_version IS NULL OR executed_policy_version >= 0",
            name="ck_follow_up_task_executed_policy_version",
        ),
        CheckConstraint(
            "target_channel IS NULL OR target_channel ~ '^[a-z][a-z0-9_-]{0,39}$'",
            name="ck_follow_up_task_target_channel",
        ),
        CheckConstraint(
            "kind != 'proposal_reminder' OR quote_version_id IS NOT NULL OR "
            "status IN ('review_required', 'completed', 'cancelled')",
            name="ck_follow_up_task_proposal_quote",
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
        UniqueConstraint(
            "chat_message_id",
            name="uq_follow_up_task_chat_message",
        ),
        UniqueConstraint(
            "outbound_message_id",
            name="uq_follow_up_task_outbound_message",
        ),
        Index(
            "ix_follow_up_task_claim",
            "status",
            "available_at",
            "due_at",
        ),
        Index(
            "ix_follow_up_task_fifo",
            "fifo_key",
            "status",
            "available_at",
        ),
        Index(
            "ix_follow_up_task_agent_status_due",
            "assigned_agent_id",
            "status",
            "due_at",
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
        ForeignKey("chat_conversations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    fifo_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
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
    executed_consent_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT"),
        nullable=True,
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
    quote_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quote_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    outbound_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_messages.id", ondelete="SET NULL"),
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
    scheduled_control_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    scheduled_automation_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    scheduled_policy_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    executed_policy_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_safe_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_required_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class FollowUpTaskEvent(Base):
    """Append-only, content-free evidence for one task state version."""

    __tablename__ = "follow_up_task_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN "
            "('scheduled', 'transitioned', 'deferred', 'legacy_quarantined')",
            name="ck_follow_up_task_event_type",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_FOLLOW_UP_STATUS_SQL})",
            name="ck_follow_up_task_event_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({_FOLLOW_UP_STATUS_SQL})",
            name="ck_follow_up_task_event_to_status",
        ),
        CheckConstraint(
            "(event_type = 'scheduled' AND state_version = 0 "
            "AND from_status IS NULL AND to_status = 'scheduled') OR "
            "(event_type = 'transitioned' AND state_version > 0 "
            "AND from_status IS NOT NULL AND from_status <> to_status) OR "
            "(event_type = 'deferred' AND state_version > 0 "
            "AND from_status = 'scheduled' AND to_status = 'scheduled') OR "
            "(event_type = 'legacy_quarantined' AND state_version > 0 "
            "AND from_status IN ('scheduled', 'in_progress') "
            "AND to_status = 'review_required')",
            name="ck_follow_up_task_event_transition",
        ),
        CheckConstraint(
            "actor_type IN ('agent', 'operator', 'worker', 'system', 'migration')",
            name="ck_follow_up_task_event_actor_type",
        ),
        CheckConstraint(
            "(actor_type = 'agent' AND actor_agent_id IS NOT NULL "
            "AND actor_admin_id IS NULL AND actor_worker_id IS NULL) OR "
            "(actor_type = 'operator' AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NOT NULL AND actor_worker_id IS NULL) OR "
            "(actor_type = 'worker' AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NULL "
            "AND char_length(btrim(actor_worker_id)) > 0) OR "
            "(actor_type IN ('system', 'migration') AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NULL AND actor_worker_id IS NULL)",
            name="ck_follow_up_task_event_actor",
        ),
        CheckConstraint(
            "event_type = 'legacy_quarantined' OR "
            "safe_code = 'legacy_follow_up_context_unknown' OR "
            "(routing_agent_id IS NOT NULL AND automation_agent_id IS NOT NULL "
            "AND char_length(btrim(target_channel)) > 0 "
            "AND control_version IS NOT NULL AND automation_version IS NOT NULL "
            "AND scheduled_policy_version IS NOT NULL)",
            name="ck_follow_up_task_event_snapshot",
        ),
        CheckConstraint(
            "control_version IS NULL OR control_version >= 0",
            name="ck_follow_up_task_event_control_version",
        ),
        CheckConstraint(
            "automation_version IS NULL OR automation_version >= 0",
            name="ck_follow_up_task_event_automation_version",
        ),
        CheckConstraint(
            "scheduled_policy_version IS NULL OR scheduled_policy_version >= 0",
            name="ck_follow_up_task_event_scheduled_policy_version",
        ),
        CheckConstraint(
            "executed_policy_version IS NULL OR executed_policy_version >= 0",
            name="ck_follow_up_task_event_executed_policy_version",
        ),
        CheckConstraint(
            "target_channel IS NULL OR target_channel ~ '^[a-z][a-z0-9_-]{0,39}$'",
            name="ck_follow_up_task_event_target_channel",
        ),
        CheckConstraint(
            "safe_code IS NULL OR char_length(btrim(safe_code)) > 0",
            name="ck_follow_up_task_event_safe_code",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_follow_up_task_event_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_follow_up_task_event_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_follow_up_task_event_idempotency",
        ),
        UniqueConstraint(
            "task_id",
            "state_version",
            name="uq_follow_up_task_event_version",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_follow_up_task_event_idempotency",
        ),
        UniqueConstraint(
            "chat_message_id",
            name="uq_follow_up_task_event_chat_message",
        ),
        UniqueConstraint(
            "outbound_message_id",
            name="uq_follow_up_task_event_outbound_message",
        ),
        Index(
            "ix_follow_up_task_event_task_created",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("follow_up_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
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
    target_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    control_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    automation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_policy_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    executed_policy_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    consent_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    executed_consent_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    outbound_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    safe_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
