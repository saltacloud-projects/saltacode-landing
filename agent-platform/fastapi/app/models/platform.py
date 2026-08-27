"""Channel-neutral conversation and identity models for the agent platform."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedModel


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
            "channel", "external_subject", name="uq_channel_identity_subject"
        ),
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
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
            "external_thread_id",
            name="uq_chat_conversation_external_thread",
        ),
        Index("ix_chat_conversation_principal_updated", "principal_id", "updated_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    external_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    route_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    channel_route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_agent_routes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
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
    """Idempotent execution record and correlation boundary for one inbound message."""

    __tablename__ = "chat_executions"

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
    status: Mapped[str] = mapped_column(String(30), default="accepted", nullable=False)
    output_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    tools_used: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
