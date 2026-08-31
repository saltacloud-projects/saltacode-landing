"""Durable, route-scoped inbox for authenticated WhatsApp messages."""

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class WhatsAppInboundJob(TimestampedModel):
    """One durable processing attempt boundary for a provider message."""

    __tablename__ = "whatsapp_inbound_jobs"
    __table_args__ = (
        UniqueConstraint(
            "channel_route_id",
            "provider_message_id",
            name="uq_whatsapp_inbound_job_route_message",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_whatsapp_inbound_job_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_whatsapp_inbound_job_attempts",
        ),
        Index(
            "ix_whatsapp_inbound_job_claim",
            "status",
            "next_attempt_at",
            "created_at",
        ),
    )

    channel_route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="queued", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
