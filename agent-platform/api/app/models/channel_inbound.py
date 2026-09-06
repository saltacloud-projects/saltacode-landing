"""Durable provider-neutral ingress with append-only lifecycle evidence."""

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
from app.models.base import TimestampedModel

CHANNEL_INBOUND_STATUSES = (
    "queued",
    "processing",
    "completed",
    "routed_to_human",
    "ignored",
    "review_required",
    "cancelled",
)
CHANNEL_INBOUND_PHASES = (
    "accepted",
    "legacy_quarantined",
    "claimed",
    "inbound_recorded",
    "provider_effect_started",
    "transcription_started",
    "agent_effect_started",
    "outbox_effect_started",
    "terminal",
)
CHANNEL_INBOUND_EVENT_TYPES = (
    "accepted",
    "legacy_completed_migrated",
    "legacy_quarantined",
    "claimed",
    "phase_advanced",
    "completed",
    "routed_to_human",
    "review_required",
    "requeued",
    "cancelled",
    "acknowledged",
)

_STATUS_SQL = ", ".join(f"'{value}'" for value in CHANNEL_INBOUND_STATUSES)
_PHASE_SQL = ", ".join(f"'{value}'" for value in CHANNEL_INBOUND_PHASES)
_EVENT_SQL = ", ".join(f"'{value}'" for value in CHANNEL_INBOUND_EVENT_TYPES)
_EVENT_FROM_STATUS_SQL = _STATUS_SQL + ", 'failed'"
_CHANNEL_SQL = "'whatsapp', 'email', 'instagram_dm', 'facebook_messenger'"
_SHA256_HEX_SQL = "'^[0-9a-f]{64}$'"


class ChannelInboundJob(TimestampedModel):
    """Current state of one authenticated external-provider message."""

    __tablename__ = "channel_inbound_jobs"
    __table_args__ = (
        UniqueConstraint(
            "channel_route_id",
            "provider_message_id",
            name="uq_channel_inbound_job_route_message",
        ),
        CheckConstraint(
            f"channel IN ({_CHANNEL_SQL})",
            name="ck_channel_inbound_job_channel",
        ),
        CheckConstraint(
            f"status IN ({_STATUS_SQL})",
            name="ck_channel_inbound_job_status",
        ),
        CheckConstraint(
            f"phase IN ({_PHASE_SQL})",
            name="ck_channel_inbound_job_phase",
        ),
        CheckConstraint(
            "state_version >= 0 AND attempts >= 0",
            name="ck_channel_inbound_job_versions",
        ),
        CheckConstraint(
            "channel_route_version >= 0 AND channel_connection_version >= 0 "
            "AND adapter_version > 0",
            name="ck_channel_inbound_job_snapshots",
        ),
        CheckConstraint(
            "thread_key IS NULL OR thread_key ~ " + _SHA256_HEX_SQL,
            name="ck_channel_inbound_job_thread_key",
        ),
        CheckConstraint(
            "payload_hash IS NULL OR payload_hash ~ " + _SHA256_HEX_SQL,
            name="ck_channel_inbound_job_payload_hash",
        ),
        CheckConstraint(
            "(payload_ciphertext IS NULL) = (payload_hash IS NULL)",
            name="ck_channel_inbound_job_payload_pair",
        ),
        CheckConstraint(
            "status NOT IN ('queued', 'processing') OR "
            "(thread_key IS NOT NULL AND payload_ciphertext IS NOT NULL "
            "AND legacy_payload_json IS NULL)",
            name="ck_channel_inbound_job_executable_payload",
        ),
        CheckConstraint(
            "(status = 'processing' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'processing' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_channel_inbound_job_lease",
        ),
        Index(
            "ix_channel_inbound_job_claim",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_channel_inbound_job_thread_fifo",
            "thread_key",
            "created_at",
            "id",
        ),
        Index(
            "ix_channel_inbound_job_agent_status",
            "routing_agent_id",
            "status",
            "updated_at",
        ),
    )

    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    route_key_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legacy_payload_json: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    safe_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_control_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    automation_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    conversation_automation_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Quarantined compatibility evidence. The neutral worker never reads these
    # columns; only the explicit legacy-review command may convert them.
    legacy_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    legacy_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legacy_locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    legacy_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legacy_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legacy_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    legacy_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChannelInboundEvent(Base):
    """Append-only receipt for each accepted message and state transition."""

    __tablename__ = "channel_inbound_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_EVENT_SQL})",
            name="ck_channel_inbound_event_type",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_EVENT_FROM_STATUS_SQL})",
            name="ck_channel_inbound_event_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({_STATUS_SQL})",
            name="ck_channel_inbound_event_to_status",
        ),
        CheckConstraint(
            f"phase IN ({_PHASE_SQL})",
            name="ck_channel_inbound_event_phase",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_channel_inbound_event_version",
        ),
        CheckConstraint(
            "actor_type IN ('system', 'worker', 'operator')",
            name="ck_channel_inbound_event_actor_type",
        ),
        CheckConstraint(
            "(actor_type = 'operator' AND actor_admin_id IS NOT NULL) OR "
            "(actor_type <> 'operator' AND actor_admin_id IS NULL)",
            name="ck_channel_inbound_event_actor",
        ),
        CheckConstraint(
            "command_hash IS NULL OR command_hash ~ " + _SHA256_HEX_SQL,
            name="ck_channel_inbound_event_command_hash",
        ),
        UniqueConstraint(
            "job_id",
            "state_version",
            name="uq_channel_inbound_event_state_version",
        ),
        UniqueConstraint(
            "job_id",
            "idempotency_key",
            name="uq_channel_inbound_event_idempotency",
        ),
        Index(
            "ix_channel_inbound_event_job_created",
            "job_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_inbound_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    safe_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(220), nullable=True)
    command_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    channel_route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    channel_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversation_control_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    automation_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversation_automation_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
