"""Durable outbound queue and immutable delivery evidence."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class OutboundMessage(TimestampedModel):
    """Mutable queue projection for one durable channel delivery command."""

    __tablename__ = "outbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_outbound_message_conversation_sequence",
        ),
        UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_outbound_message_conversation_idempotency",
        ),
        UniqueConstraint(
            "channel_route_id",
            "provider_message_id",
            name="uq_outbound_message_route_provider_id",
        ),
        CheckConstraint(
            "sender_type IN ('automation', 'operator', 'system')",
            name="ck_outbound_message_sender_type",
        ),
        CheckConstraint(
            "kind IN ('text', 'image', 'document', 'template', 'interactive')",
            name="ck_outbound_message_kind",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_outbound_message_payload_object",
        ),
        CheckConstraint(
            "(kind = 'text' AND jsonb_typeof(payload_json -> 'text') = 'string') "
            "OR (kind IN ('image', 'document') "
            "AND jsonb_typeof(payload_json -> 'storage_key') = 'string' "
            "AND jsonb_typeof(payload_json -> 'name') = 'string' "
            "AND jsonb_typeof(payload_json -> 'mime') = 'string') "
            "OR (kind = 'template' "
            "AND jsonb_typeof(payload_json -> 'template_key') = 'string' "
            "AND jsonb_typeof(payload_json -> 'language') = 'string') "
            "OR (kind = 'interactive' "
            "AND jsonb_typeof(payload_json -> 'body') = 'string' "
            "AND jsonb_typeof(payload_json -> 'actions') = 'array')",
            name="ck_outbound_message_payload_shape",
        ),
        CheckConstraint(
            "status IN ('queued', 'dispatching', 'accepted', 'delivered', "
            "'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_message_status",
        ),
        CheckConstraint(
            "control_version >= 0 "
            "AND (automation_version IS NULL OR automation_version >= 0) "
            "AND sequence > 0 AND last_attempt_number >= 0",
            name="ck_outbound_message_counters",
        ),
        CheckConstraint(
            "(automation_agent_id IS NULL) = (automation_version IS NULL)",
            name="ck_outbound_message_automation_snapshot_pair",
        ),
        CheckConstraint(
            "(channel IS NULL AND adapter_key IS NULL "
            "AND channel_connection_id IS NULL AND route_version IS NULL "
            "AND connection_version IS NULL) OR "
            "(channel IS NOT NULL AND adapter_key IS NOT NULL "
            "AND channel_connection_id IS NOT NULL AND route_version IS NOT NULL "
            "AND connection_version IS NOT NULL)",
            name="ck_outbound_message_route_snapshot_set",
        ),
        CheckConstraint(
            "(route_version IS NULL OR route_version >= 0) "
            "AND (connection_version IS NULL OR connection_version >= 0)",
            name="ck_outbound_message_route_snapshot_versions",
        ),
        CheckConstraint(
            "status NOT IN ('queued', 'dispatching') OR channel IS NOT NULL",
            name="ck_outbound_message_active_route_snapshot",
        ),
        CheckConstraint(
            "char_length(idempotency_key) > 0 "
            "AND char_length(destination) > 0 "
            "AND char_length(correlation_id) > 0 "
            "AND char_length(payload_hash) = 64",
            name="ck_outbound_message_command_identity",
        ),
        CheckConstraint(
            "(sender_type = 'operator' AND sender_admin_id IS NOT NULL) OR "
            "(sender_type != 'operator' AND sender_admin_id IS NULL)",
            name="ck_outbound_message_sender_actor",
        ),
        CheckConstraint(
            "(status = 'dispatching' AND locked_by IS NOT NULL "
            "AND locked_at IS NOT NULL) OR "
            "(status != 'dispatching' AND locked_by IS NULL AND locked_at IS NULL)",
            name="ck_outbound_message_dispatch_lock",
        ),
        CheckConstraint(
            "status NOT IN ('accepted', 'delivered', 'read') "
            "OR provider_message_id IS NOT NULL",
            name="ck_outbound_message_accepted_provider_id",
        ),
        Index(
            "ix_outbound_message_claim",
            "status",
            "created_at",
        ),
        Index(
            "ix_outbound_message_conversation_status_sequence",
            "conversation_id",
            "status",
            "sequence",
        ),
        Index(
            "ix_outbound_message_agent_status_created",
            "agent_id",
            "status",
            "created_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel_route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    adapter_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    channel_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_connections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    route_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connection_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    automation_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    automation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    last_attempt_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OutboundAttempt(Base):
    """Immutable fact that a worker claimed one delivery attempt."""

    __tablename__ = "outbound_attempts"
    __table_args__ = (
        UniqueConstraint(
            "outbound_message_id",
            "attempt_number",
            name="uq_outbound_attempt_message_number",
        ),
        CheckConstraint(
            "attempt_number > 0 AND control_version >= 0",
            name="ck_outbound_attempt_counters",
        ),
        CheckConstraint(
            "char_length(worker_id) > 0",
            name="ck_outbound_attempt_worker",
        ),
        Index(
            "ix_outbound_attempt_message_created",
            "outbound_message_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    outbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboundDeliveryEvent(Base):
    """Immutable, body-free evidence for one outbound state transition."""

    __tablename__ = "outbound_delivery_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('enqueued', 'claimed', 'accepted', 'delivered', "
            "'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_delivery_event_type",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('queued', 'dispatching', "
            "'accepted', 'delivered', 'read', 'failed', 'delivery_unknown', "
            "'cancelled')",
            name="ck_outbound_delivery_event_from_status",
        ),
        CheckConstraint(
            "to_status IN ('queued', 'dispatching', 'accepted', 'delivered', "
            "'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_delivery_event_to_status",
        ),
        CheckConstraint(
            "actor_type IN ('automation', 'operator', 'system', 'worker', 'provider')",
            name="ck_outbound_delivery_event_actor_type",
        ),
        CheckConstraint(
            "(actor_type IN ('operator', 'worker') AND actor_id IS NOT NULL) OR "
            "(actor_type NOT IN ('operator', 'worker'))",
            name="ck_outbound_delivery_event_actor",
        ),
        CheckConstraint(
            "safe_code IS NULL OR safe_code ~ '^[A-Za-z0-9_.:-]{1,80}$'",
            name="ck_outbound_delivery_event_safe_code",
        ),
        CheckConstraint(
            "(event_type = 'enqueued' AND to_status = 'queued') OR "
            "(event_type = 'claimed' AND to_status = 'dispatching') OR "
            "(event_type NOT IN ('enqueued', 'claimed') AND event_type = to_status)",
            name="ck_outbound_delivery_event_transition",
        ),
        Index(
            "ix_outbound_delivery_event_message_created",
            "outbound_message_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    outbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    safe_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
