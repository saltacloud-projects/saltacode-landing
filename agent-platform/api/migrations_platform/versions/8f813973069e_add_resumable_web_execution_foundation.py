"""Add resumable conversation events and durable web executions.

Revision ID: 8f813973069e
Revises: 7e702862958d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8f813973069e"
down_revision: str | None = "7e702862958d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_conversations",
        sa.Column(
            "next_event_sequence",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_chat_conversation_next_event_sequence",
        "chat_conversations",
        "next_event_sequence > 0",
    )

    op.add_column(
        "chat_executions",
        sa.Column("client_message_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "chat_executions",
        sa.Column("input_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "chat_executions",
        sa.Column("queue_sequence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_executions",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_executions",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_executions",
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "chat_executions",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "chat_executions",
        "status",
        existing_type=sa.String(length=30),
        server_default=sa.text("'queued'"),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_chat_execution_status",
        "chat_executions",
        "status IN ('accepted', 'queued', 'running', 'completed', 'failed', "
        "'blocked', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_chat_execution_attempt_count",
        "chat_executions",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_chat_execution_lease_pair",
        "chat_executions",
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_chat_execution_client_hash",
        "chat_executions",
        "(client_message_id IS NULL AND input_hash IS NULL AND "
        "queue_sequence IS NULL) OR (client_message_id IS NOT NULL AND "
        "char_length(input_hash) = 64 AND queue_sequence > 0)",
    )
    op.create_check_constraint(
        "ck_chat_execution_lease_owner",
        "chat_executions",
        "lease_owner IS NULL OR char_length(lease_owner) > 0",
    )
    op.create_unique_constraint(
        "uq_chat_execution_conversation_client_message",
        "chat_executions",
        ["conversation_id", "client_message_id"],
    )
    op.create_unique_constraint(
        "uq_chat_execution_conversation_queue_sequence",
        "chat_executions",
        ["conversation_id", "queue_sequence"],
    )
    op.create_index(
        "ix_chat_execution_durable_claim",
        "chat_executions",
        ["status", "available_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_chat_execution_expired_lease",
        "chat_executions",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running' AND lease_expires_at IS NOT NULL"),
    )

    op.create_table(
        "conversation_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("visibility", sa.String(length=12), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9]*(\\.[a-z0-9]+){1,5}$'",
            name="ck_conversation_event_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_conversation_event_payload_object",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_conversation_event_sequence",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_conversation_event_visibility",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_event_agent_created",
        "conversation_events",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_events_agent_id"),
        "conversation_events",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_events_conversation_id"),
        "conversation_events",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "uq_conversation_event_sequence",
        "conversation_events",
        ["conversation_id", "sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_conversation_event_sequence", table_name="conversation_events")
    op.drop_index(
        op.f("ix_conversation_events_conversation_id"),
        table_name="conversation_events",
    )
    op.drop_index(
        op.f("ix_conversation_events_agent_id"),
        table_name="conversation_events",
    )
    op.drop_index(
        "ix_conversation_event_agent_created", table_name="conversation_events"
    )
    op.drop_table("conversation_events")

    op.drop_index("ix_chat_execution_expired_lease", table_name="chat_executions")
    op.drop_index("ix_chat_execution_durable_claim", table_name="chat_executions")
    op.drop_constraint(
        "uq_chat_execution_conversation_queue_sequence",
        "chat_executions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_chat_execution_conversation_client_message",
        "chat_executions",
        type_="unique",
    )
    op.drop_constraint(
        "ck_chat_execution_lease_owner", "chat_executions", type_="check"
    )
    op.drop_constraint(
        "ck_chat_execution_client_hash", "chat_executions", type_="check"
    )
    op.drop_constraint("ck_chat_execution_lease_pair", "chat_executions", type_="check")
    op.drop_constraint(
        "ck_chat_execution_attempt_count", "chat_executions", type_="check"
    )
    op.drop_constraint("ck_chat_execution_status", "chat_executions", type_="check")
    op.alter_column(
        "chat_executions",
        "status",
        existing_type=sa.String(length=30),
        server_default=None,
        existing_nullable=False,
    )
    op.drop_column("chat_executions", "lease_expires_at")
    op.drop_column("chat_executions", "lease_owner")
    op.drop_column("chat_executions", "available_at")
    op.drop_column("chat_executions", "attempt_count")
    op.drop_column("chat_executions", "queue_sequence")
    op.drop_column("chat_executions", "input_hash")
    op.drop_column("chat_executions", "client_message_id")

    op.drop_constraint(
        "ck_chat_conversation_next_event_sequence",
        "chat_conversations",
        type_="check",
    )
    op.drop_column("chat_conversations", "next_event_sequence")
