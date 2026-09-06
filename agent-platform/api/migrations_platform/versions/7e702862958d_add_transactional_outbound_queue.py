"""Add the transactional outbound delivery queue.

Revision ID: 7e702862958d
Revises: d7e8f9a0b1c2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7e702862958d"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_messages",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("channel_route_id", sa.UUID(), nullable=False),
        sa.Column("chat_message_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("sender_type", sa.String(length=20), nullable=False),
        sa.Column("sender_admin_id", sa.UUID(), nullable=True),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_attempt_number", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
            "(sender_type = 'operator' AND sender_admin_id IS NOT NULL) OR (sender_type != 'operator' AND sender_admin_id IS NULL)",
            name="ck_outbound_message_sender_actor",
        ),
        sa.CheckConstraint(
            "sender_type IN ('automation', 'operator', 'system')",
            name="ck_outbound_message_sender_type",
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'image', 'document', 'template', 'interactive')",
            name="ck_outbound_message_kind",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_outbound_message_payload_object",
        ),
        sa.CheckConstraint(
            "(kind = 'text' AND jsonb_typeof(payload_json -> 'text') = 'string') OR (kind IN ('image', 'document') AND jsonb_typeof(payload_json -> 'storage_key') = 'string' AND jsonb_typeof(payload_json -> 'name') = 'string' AND jsonb_typeof(payload_json -> 'mime') = 'string') OR (kind = 'template' AND jsonb_typeof(payload_json -> 'template_key') = 'string' AND jsonb_typeof(payload_json -> 'language') = 'string') OR (kind = 'interactive' AND jsonb_typeof(payload_json -> 'body') = 'string' AND jsonb_typeof(payload_json -> 'actions') = 'array')",
            name="ck_outbound_message_payload_shape",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'dispatching', 'accepted', 'delivered', 'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_message_status",
        ),
        sa.CheckConstraint(
            "control_version >= 0 AND sequence > 0 AND last_attempt_number >= 0",
            name="ck_outbound_message_counters",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) > 0 AND char_length(correlation_id) > 0 AND char_length(payload_hash) = 64",
            name="ck_outbound_message_command_identity",
        ),
        sa.CheckConstraint(
            "(status = 'dispatching' AND locked_by IS NOT NULL AND locked_at IS NOT NULL) OR (status != 'dispatching' AND locked_by IS NULL AND locked_at IS NULL)",
            name="ck_outbound_message_dispatch_lock",
        ),
        sa.CheckConstraint(
            "status NOT IN ('accepted', 'delivered', 'read') OR provider_message_id IS NOT NULL",
            name="ck_outbound_message_accepted_provider_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["channel_route_id"], ["channel_agent_routes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"], ["chat_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sender_admin_id"], ["admin_users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_outbound_message_conversation_idempotency",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_outbound_message_conversation_sequence",
        ),
        sa.UniqueConstraint(
            "channel_route_id",
            "provider_message_id",
            name="uq_outbound_message_route_provider_id",
        ),
    )
    op.create_index(
        "ix_outbound_message_agent_status_created",
        "outbound_messages",
        ["agent_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_outbound_message_claim",
        "outbound_messages",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_outbound_message_conversation_status_sequence",
        "outbound_messages",
        ["conversation_id", "status", "sequence"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_messages_channel_route_id"),
        "outbound_messages",
        ["channel_route_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_messages_chat_message_id"),
        "outbound_messages",
        ["chat_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_messages_correlation_id"),
        "outbound_messages",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_messages_locked_at"),
        "outbound_messages",
        ["locked_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_messages_provider_message_id"),
        "outbound_messages",
        ["provider_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_messages_sender_admin_id"),
        "outbound_messages",
        ["sender_admin_id"],
        unique=False,
    )
    op.create_table(
        "outbound_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("outbound_message_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_number > 0 AND control_version >= 0",
            name="ck_outbound_attempt_counters",
        ),
        sa.CheckConstraint(
            "char_length(worker_id) > 0",
            name="ck_outbound_attempt_worker",
        ),
        sa.ForeignKeyConstraint(
            ["outbound_message_id"], ["outbound_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "outbound_message_id",
            "attempt_number",
            name="uq_outbound_attempt_message_number",
        ),
    )
    op.create_index(
        "ix_outbound_attempt_message_created",
        "outbound_attempts",
        ["outbound_message_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "outbound_delivery_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("outbound_message_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column("safe_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('automation', 'operator', 'system', 'worker', 'provider')",
            name="ck_outbound_delivery_event_actor_type",
        ),
        sa.CheckConstraint(
            "(actor_type IN ('operator', 'worker') AND actor_id IS NOT NULL) OR (actor_type NOT IN ('operator', 'worker'))",
            name="ck_outbound_delivery_event_actor",
        ),
        sa.CheckConstraint(
            "event_type IN ('enqueued', 'claimed', 'accepted', 'delivered', 'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_delivery_event_type",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('queued', 'dispatching', 'accepted', 'delivered', 'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_delivery_event_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('queued', 'dispatching', 'accepted', 'delivered', 'read', 'failed', 'delivery_unknown', 'cancelled')",
            name="ck_outbound_delivery_event_to_status",
        ),
        sa.CheckConstraint(
            "safe_code IS NULL OR safe_code ~ '^[A-Za-z0-9_.:-]{1,80}$'",
            name="ck_outbound_delivery_event_safe_code",
        ),
        sa.CheckConstraint(
            "(event_type = 'enqueued' AND to_status = 'queued') OR (event_type = 'claimed' AND to_status = 'dispatching') OR (event_type NOT IN ('enqueued', 'claimed') AND event_type = to_status)",
            name="ck_outbound_delivery_event_transition",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["outbound_attempts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["outbound_message_id"], ["outbound_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbound_delivery_event_message_created",
        "outbound_delivery_events",
        ["outbound_message_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbound_delivery_events_attempt_id"),
        "outbound_delivery_events",
        ["attempt_id"],
        unique=False,
    )
    op.add_column(
        "chat_conversations",
        sa.Column(
            "next_outbound_sequence",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_chat_conversation_next_outbound_sequence",
        "chat_conversations",
        "next_outbound_sequence > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_chat_conversation_next_outbound_sequence",
        "chat_conversations",
        type_="check",
    )
    op.drop_column("chat_conversations", "next_outbound_sequence")
    op.drop_index(
        op.f("ix_outbound_delivery_events_attempt_id"),
        table_name="outbound_delivery_events",
    )
    op.drop_index(
        "ix_outbound_delivery_event_message_created",
        table_name="outbound_delivery_events",
    )
    op.drop_table("outbound_delivery_events")
    op.drop_index("ix_outbound_attempt_message_created", table_name="outbound_attempts")
    op.drop_table("outbound_attempts")
    op.drop_index(
        op.f("ix_outbound_messages_sender_admin_id"), table_name="outbound_messages"
    )
    op.drop_index(
        op.f("ix_outbound_messages_provider_message_id"), table_name="outbound_messages"
    )
    op.drop_index(
        op.f("ix_outbound_messages_locked_at"), table_name="outbound_messages"
    )
    op.drop_index(
        op.f("ix_outbound_messages_correlation_id"), table_name="outbound_messages"
    )
    op.drop_index(
        op.f("ix_outbound_messages_chat_message_id"), table_name="outbound_messages"
    )
    op.drop_index(
        op.f("ix_outbound_messages_channel_route_id"), table_name="outbound_messages"
    )
    op.drop_index(
        "ix_outbound_message_conversation_status_sequence",
        table_name="outbound_messages",
    )
    op.drop_index("ix_outbound_message_claim", table_name="outbound_messages")
    op.drop_index(
        "ix_outbound_message_agent_status_created", table_name="outbound_messages"
    )
    op.drop_table("outbound_messages")
