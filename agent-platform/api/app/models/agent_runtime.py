"""Persisted provider, channel, routing, and per-agent runtime configuration."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
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


class ProviderConnection(TimestampedModel):
    __tablename__ = "provider_connections"
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('openai')", name="ck_provider_connection_type"
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    provider_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="openai"
    )
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    settings_json: Mapped[dict] = mapped_column(
        "settings", JSONB, default=dict, nullable=False
    )
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class AgentRuntimeConfig(TimestampedModel):
    __tablename__ = "agent_runtime_configs"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_runtime_config_agent"),
        CheckConstraint(
            "temperature >= 0 AND temperature <= 2", name="ck_agent_runtime_temperature"
        ),
        CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 128000",
            name="ck_agent_runtime_output_tokens",
        ),
        CheckConstraint(
            "max_iterations BETWEEN 1 AND 50", name="ck_agent_runtime_iterations"
        ),
        CheckConstraint(
            "max_tool_calls BETWEEN 0 AND 200", name="ck_agent_runtime_tool_calls"
        ),
        CheckConstraint(
            "loop_timeout_seconds BETWEEN 1 AND 900",
            name="ck_agent_runtime_loop_timeout",
        ),
        CheckConstraint(
            "tool_timeout_seconds BETWEEN 1 AND 300",
            name="ck_agent_runtime_tool_timeout",
        ),
        CheckConstraint(
            "tool_result_max_chars BETWEEN 256 AND 100000",
            name="ck_agent_runtime_tool_result_cap",
        ),
        CheckConstraint(
            "history_message_limit BETWEEN 0 AND 200",
            name="ck_agent_runtime_history_limit",
        ),
        CheckConstraint(
            "history_cache_ttl_seconds BETWEEN 0 AND 86400",
            name="ck_agent_runtime_history_cache_ttl",
        ),
        CheckConstraint(
            "summary_trigger_messages BETWEEN 1 AND 1000",
            name="ck_agent_runtime_summary_trigger",
        ),
        CheckConstraint(
            "summary_max_chars BETWEEN 1000 AND 500000",
            name="ck_agent_runtime_summary_cap",
        ),
        CheckConstraint(
            "rag_retrieval_top_k BETWEEN 1 AND 50", name="ck_agent_runtime_rag_top_k"
        ),
        CheckConstraint(
            "rag_min_relevance_score BETWEEN 0 AND 1",
            name="ck_agent_runtime_rag_min_score",
        ),
        CheckConstraint(
            "rag_vector_weight BETWEEN 0 AND 1 AND rag_lexical_weight BETWEEN 0 AND 1 AND abs((rag_vector_weight + rag_lexical_weight) - 1.0) <= 0.000001",
            name="ck_agent_runtime_rag_weights",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    chat_model: Mapped[str] = mapped_column(String(160), nullable=False)
    transcription_model: Mapped[str] = mapped_column(String(160), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2000
    )
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    max_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    loop_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=150
    )
    tool_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    tool_result_max_chars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=16000
    )
    history_message_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20
    )
    history_cache_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    summary_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    summary_trigger_messages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10
    )
    summary_max_chars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60000
    )
    rag_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rag_retrieval_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    rag_min_relevance_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.35
    )
    rag_vector_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    rag_lexical_weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.3
    )
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class ChannelConnection(TimestampedModel):
    __tablename__ = "channel_connections"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('web', 'whatsapp')", name="ck_channel_connection_channel"
        ),
        UniqueConstraint(
            "channel", "external_account_id", name="uq_channel_connection_account"
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings_json: Mapped[dict] = mapped_column(
        "settings", JSONB, default=dict, nullable=False
    )
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class ChannelAgentRoute(TimestampedModel):
    __tablename__ = "channel_agent_routes"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('web', 'whatsapp')", name="ck_channel_agent_route_channel"
        ),
        CheckConstraint(
            "route_key ~ '^[a-z0-9][a-z0-9._:-]{0,119}$'",
            name="ck_channel_agent_route_key",
        ),
        UniqueConstraint("channel", "route_key", name="uq_channel_agent_route_key"),
        Index("ix_channel_agent_route_agent_active", "agent_id", "is_active"),
    )

    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    route_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
