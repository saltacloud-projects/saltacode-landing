"""add per-agent runtime configuration and channel routing

Revision ID: a31e4d8b27f0
Revises: 6c9c18a6f821
Create Date: 2026-08-27 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import settings

revision: str = "a31e4d8b27f0"
down_revision: str | None = "6c9c18a6f821"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("provider_type", sa.String(30), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=True),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=True),
        sa.Column("updated_by", sa.String(160), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider_type IN ('openai')", name="ck_provider_connection_type"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_provider_connections_slug", "provider_connections", ["slug"], unique=True
    )
    op.create_index(
        "ix_provider_connections_is_active", "provider_connections", ["is_active"]
    )

    op.create_table(
        "agent_runtime_configs",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("provider_connection_id", sa.UUID(), nullable=True),
        sa.Column("chat_model", sa.String(160), nullable=False),
        sa.Column("transcription_model", sa.String(160), nullable=False),
        sa.Column("temperature", sa.Float(), server_default="0.5", nullable=False),
        sa.Column(
            "max_output_tokens", sa.Integer(), server_default="2000", nullable=False
        ),
        sa.Column("max_iterations", sa.Integer(), server_default="12", nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), server_default="25", nullable=False),
        sa.Column(
            "loop_timeout_seconds", sa.Integer(), server_default="150", nullable=False
        ),
        sa.Column(
            "tool_timeout_seconds", sa.Integer(), server_default="60", nullable=False
        ),
        sa.Column(
            "tool_result_max_chars",
            sa.Integer(),
            server_default="16000",
            nullable=False,
        ),
        sa.Column(
            "history_message_limit", sa.Integer(), server_default="20", nullable=False
        ),
        sa.Column(
            "history_cache_ttl_seconds",
            sa.Integer(),
            server_default="300",
            nullable=False,
        ),
        sa.Column(
            "summary_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "summary_trigger_messages",
            sa.Integer(),
            server_default="10",
            nullable=False,
        ),
        sa.Column(
            "summary_max_chars", sa.Integer(), server_default="60000", nullable=False
        ),
        sa.Column(
            "rag_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "rag_retrieval_top_k", sa.Integer(), server_default="8", nullable=False
        ),
        sa.Column(
            "rag_min_relevance_score", sa.Float(), server_default="0.35", nullable=False
        ),
        sa.Column(
            "rag_vector_weight", sa.Float(), server_default="0.7", nullable=False
        ),
        sa.Column(
            "rag_lexical_weight", sa.Float(), server_default="0.3", nullable=False
        ),
        sa.Column("created_by", sa.String(160), nullable=True),
        sa.Column("updated_by", sa.String(160), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "temperature >= 0 AND temperature <= 2", name="ck_agent_runtime_temperature"
        ),
        sa.CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 128000",
            name="ck_agent_runtime_output_tokens",
        ),
        sa.CheckConstraint(
            "max_iterations BETWEEN 1 AND 50", name="ck_agent_runtime_iterations"
        ),
        sa.CheckConstraint(
            "max_tool_calls BETWEEN 0 AND 200", name="ck_agent_runtime_tool_calls"
        ),
        sa.CheckConstraint(
            "loop_timeout_seconds BETWEEN 1 AND 900",
            name="ck_agent_runtime_loop_timeout",
        ),
        sa.CheckConstraint(
            "tool_timeout_seconds BETWEEN 1 AND 300",
            name="ck_agent_runtime_tool_timeout",
        ),
        sa.CheckConstraint(
            "tool_result_max_chars BETWEEN 256 AND 100000",
            name="ck_agent_runtime_tool_result_cap",
        ),
        sa.CheckConstraint(
            "history_message_limit BETWEEN 0 AND 200",
            name="ck_agent_runtime_history_limit",
        ),
        sa.CheckConstraint(
            "history_cache_ttl_seconds BETWEEN 0 AND 86400",
            name="ck_agent_runtime_history_cache_ttl",
        ),
        sa.CheckConstraint(
            "summary_trigger_messages BETWEEN 1 AND 1000",
            name="ck_agent_runtime_summary_trigger",
        ),
        sa.CheckConstraint(
            "summary_max_chars BETWEEN 1000 AND 500000",
            name="ck_agent_runtime_summary_cap",
        ),
        sa.CheckConstraint(
            "rag_retrieval_top_k BETWEEN 1 AND 50", name="ck_agent_runtime_rag_top_k"
        ),
        sa.CheckConstraint(
            "rag_min_relevance_score BETWEEN 0 AND 1",
            name="ck_agent_runtime_rag_min_score",
        ),
        sa.CheckConstraint(
            "rag_vector_weight BETWEEN 0 AND 1 AND rag_lexical_weight BETWEEN 0 AND 1 AND abs((rag_vector_weight + rag_lexical_weight) - 1.0) <= 0.000001",
            name="ck_agent_runtime_rag_weights",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["provider_connection_id"], ["provider_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_runtime_config_agent"),
    )
    op.create_index(
        "ix_agent_runtime_configs_agent_id", "agent_runtime_configs", ["agent_id"]
    )
    op.create_index(
        "ix_agent_runtime_configs_provider_connection_id",
        "agent_runtime_configs",
        ["provider_connection_id"],
    )

    op.create_table(
        "channel_connections",
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("external_account_id", sa.String(255), nullable=True),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=True),
        sa.Column("updated_by", sa.String(160), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IN ('web', 'whatsapp')", name="ck_channel_connection_channel"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel", "external_account_id", name="uq_channel_connection_account"
        ),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_channel_connections_slug", "channel_connections", ["slug"], unique=True
    )
    op.create_index(
        "ix_channel_connections_channel", "channel_connections", ["channel"]
    )
    op.create_index(
        "ix_channel_connections_is_active", "channel_connections", ["is_active"]
    )

    op.create_table(
        "channel_agent_routes",
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("route_key", sa.String(120), nullable=False),
        sa.Column("channel_connection_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=True),
        sa.Column("updated_by", sa.String(160), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IN ('web', 'whatsapp')", name="ck_channel_agent_route_channel"
        ),
        sa.CheckConstraint(
            "route_key ~ '^[a-z0-9][a-z0-9._:-]{0,119}$'",
            name="ck_channel_agent_route_key",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["channel_connection_id"], ["channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "route_key", name="uq_channel_agent_route_key"),
    )
    for column in (
        "channel",
        "route_key",
        "channel_connection_id",
        "agent_id",
        "is_active",
    ):
        op.create_index(
            f"ix_channel_agent_routes_{column}", "channel_agent_routes", [column]
        )
    op.create_index(
        "ix_channel_agent_route_agent_active",
        "channel_agent_routes",
        ["agent_id", "is_active"],
    )

    op.add_column(
        "chat_conversations", sa.Column("route_key", sa.String(120), nullable=True)
    )
    op.add_column(
        "chat_conversations", sa.Column("channel_route_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_chat_conversation_channel_route",
        "chat_conversations",
        "channel_agent_routes",
        ["channel_route_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chat_conversations_route_key", "chat_conversations", ["route_key"]
    )
    op.create_index(
        "ix_chat_conversations_channel_route_id",
        "chat_conversations",
        ["channel_route_id"],
    )

    default_slug = settings.default_agent_slug.strip()
    if default_slug:
        op.execute(
            sa.text("""
                INSERT INTO agent_runtime_configs (
                    id, agent_id, chat_model, transcription_model, temperature,
                    max_output_tokens, max_iterations, max_tool_calls,
                    loop_timeout_seconds, tool_timeout_seconds, tool_result_max_chars,
                    history_message_limit, history_cache_ttl_seconds,
                    summary_enabled, summary_trigger_messages, summary_max_chars,
                    rag_enabled, rag_retrieval_top_k, rag_min_relevance_score,
                    rag_vector_weight, rag_lexical_weight, created_by, updated_by
                )
                SELECT gen_random_uuid(), p.id, :chat_model, :transcription_model, 0.5,
                    2000, 12, 25, 150, 60, 16000, 20, 300,
                    :summary_enabled, :summary_trigger, :summary_max,
                    COALESCE(r.enabled, false), COALESCE(r.retrieval_top_k, 8),
                    COALESCE(r.min_relevance_score, 0.35),
                    CASE
                        WHEN r.vector_weight BETWEEN 0 AND 1
                         AND r.lexical_weight BETWEEN 0 AND 1
                         AND abs((r.vector_weight + r.lexical_weight) - 1.0) <= 0.000001
                        THEN r.vector_weight ELSE 0.7
                    END,
                    CASE
                        WHEN r.vector_weight BETWEEN 0 AND 1
                         AND r.lexical_weight BETWEEN 0 AND 1
                         AND abs((r.vector_weight + r.lexical_weight) - 1.0) <= 0.000001
                        THEN r.lexical_weight ELSE 0.3
                    END,
                    'migration', 'migration'
                FROM agent_profiles p LEFT JOIN rag_settings r ON r.key = 'default'
                WHERE p.slug = :default_slug
                ON CONFLICT (agent_id) DO NOTHING
            """).bindparams(
                sa.bindparam("default_slug", default_slug, literal_execute=True),
                sa.bindparam("chat_model", settings.openai_model, literal_execute=True),
                sa.bindparam(
                    "transcription_model",
                    settings.openai_whisper_model,
                    literal_execute=True,
                ),
                sa.bindparam(
                    "summary_enabled",
                    settings.memory_summary_enabled,
                    literal_execute=True,
                ),
                sa.bindparam(
                    "summary_trigger",
                    settings.memory_summary_trigger_messages,
                    literal_execute=True,
                ),
                sa.bindparam(
                    "summary_max",
                    settings.memory_summary_max_chars,
                    literal_execute=True,
                ),
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_conversations_channel_route_id", table_name="chat_conversations"
    )
    op.drop_index("ix_chat_conversations_route_key", table_name="chat_conversations")
    op.drop_constraint(
        "fk_chat_conversation_channel_route", "chat_conversations", type_="foreignkey"
    )
    op.drop_column("chat_conversations", "channel_route_id")
    op.drop_column("chat_conversations", "route_key")
    op.drop_table("channel_agent_routes")
    op.drop_table("channel_connections")
    op.drop_table("agent_runtime_configs")
    op.drop_table("provider_connections")
