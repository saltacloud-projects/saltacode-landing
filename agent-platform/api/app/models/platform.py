"""Channel-neutral conversation and identity models for the agent platform."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedModel


def _default_automation_agent_id(context: Any) -> uuid.UUID:
    """Default the acting agent to the conversation routing owner."""

    return context.get_current_parameters()["agent_id"]


class Principal(TimestampedModel):
    """Internal identity shared by one or more verified channel identities."""

    __tablename__ = "principals"

    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), default="anonymous", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    identities: Mapped[list["ChannelIdentity"]] = relationship(
        back_populates="principal", cascade="all, delete-orphan"
    )


class ChannelIdentity(TimestampedModel):
    """Provider identity without leaking transport details into application policy."""

    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "route_key",
            "external_subject",
            name="uq_channel_identity_subject",
        ),
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    route_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    principal: Mapped[Principal] = relationship(back_populates="identities")


class ChatConversation(TimestampedModel):
    """Conversation owned by an agent and a principal, independent of delivery channel."""

    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "channel",
            "route_key",
            "external_thread_id",
            name="uq_chat_conversation_external_thread",
        ),
        Index("ix_chat_conversation_principal_updated", "principal_id", "updated_at"),
        Index(
            "ix_chat_conversation_agent_control_updated",
            "agent_id",
            "control_mode",
            "updated_at",
        ),
        Index(
            "ix_chat_conversation_automation_status_updated",
            "automation_agent_id",
            "status",
            "updated_at",
        ),
        CheckConstraint(
            "control_mode IN ('automated', 'paused', 'human', 'closed')",
            name="ck_chat_conversation_control_mode",
        ),
        CheckConstraint(
            "control_version >= 0",
            name="ck_chat_conversation_control_version",
        ),
        CheckConstraint(
            "automation_version >= 0",
            name="ck_chat_conversation_automation_version",
        ),
        CheckConstraint(
            "control_mode != 'human' OR assigned_admin_id IS NOT NULL",
            name="ck_chat_conversation_human_assignment",
        ),
        CheckConstraint(
            "next_outbound_sequence > 0",
            name="ck_chat_conversation_next_outbound_sequence",
        ),
        CheckConstraint(
            "next_event_sequence > 0",
            name="ck_chat_conversation_next_event_sequence",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    automation_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        default=_default_automation_agent_id,
    )
    automation_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    external_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    route_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    channel_route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_agent_routes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    control_mode: Mapped[str] = mapped_column(
        String(20), default="automated", nullable=False
    )
    control_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_outbound_sequence: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    next_event_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    control_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    control_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    transcript_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ChatMessage(TimestampedModel):
    """Durable message with channel idempotency and delivery-neutral content."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "client_message_id", name="uq_chat_message_client_id"
        ),
        Index("ix_chat_message_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    client_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    tool_names: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")


class ChatExecution(TimestampedModel):
    """Execution record shared by the legacy synchronous path and durable web queue."""

    __tablename__ = "chat_executions"
    __table_args__ = (
        CheckConstraint(
            "control_version >= 0",
            name="ck_chat_execution_control_version",
        ),
        CheckConstraint(
            "automation_version >= 0",
            name="ck_chat_execution_automation_version",
        ),
        CheckConstraint(
            "status IN ('accepted', 'queued', 'running', 'completed', 'failed', "
            "'blocked', 'cancelled')",
            name="ck_chat_execution_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_chat_execution_attempt_count",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_chat_execution_lease_pair",
        ),
        CheckConstraint(
            "(client_message_id IS NULL AND input_hash IS NULL AND "
            "queue_sequence IS NULL) OR (client_message_id IS NOT NULL AND "
            "char_length(input_hash) = 64 AND queue_sequence > 0)",
            name="ck_chat_execution_client_hash",
        ),
        CheckConstraint(
            "lease_owner IS NULL OR char_length(lease_owner) > 0",
            name="ck_chat_execution_lease_owner",
        ),
        UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_chat_execution_conversation_client_message",
        ),
        UniqueConstraint(
            "conversation_id",
            "queue_sequence",
            name="uq_chat_execution_conversation_queue_sequence",
        ),
        Index(
            "ix_chat_execution_durable_claim",
            "status",
            "available_at",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_chat_execution_expired_lease",
            "lease_expires_at",
            postgresql_where=text(
                "status = 'running' AND lease_expires_at IS NOT NULL"
            ),
        ),
    )

    request_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    inbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    automation_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    automation_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    client_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queue_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    output_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    tools_used: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
