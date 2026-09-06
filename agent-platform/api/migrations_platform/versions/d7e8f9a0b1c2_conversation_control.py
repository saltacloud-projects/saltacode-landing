"""Add auditable human control for conversations.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_conversations",
        sa.Column(
            "control_mode",
            sa.String(length=20),
            server_default=sa.text("'automated'"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_conversations",
        sa.Column(
            "control_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_conversations",
        sa.Column("assigned_admin_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "chat_conversations",
        sa.Column(
            "control_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_conversations",
        sa.Column("control_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_chat_conversations_assigned_admin_id_admin_users"),
        "chat_conversations",
        "admin_users",
        ["assigned_admin_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_chat_conversation_control_mode",
        "chat_conversations",
        "control_mode IN ('automated', 'paused', 'human', 'closed')",
    )
    op.create_check_constraint(
        "ck_chat_conversation_control_version",
        "chat_conversations",
        "control_version >= 0",
    )
    op.create_check_constraint(
        "ck_chat_conversation_human_assignment",
        "chat_conversations",
        "control_mode != 'human' OR assigned_admin_id IS NOT NULL",
    )
    op.create_index(
        op.f("ix_chat_conversations_assigned_admin_id"),
        "chat_conversations",
        ["assigned_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_conversation_agent_control_updated",
        "chat_conversations",
        ["agent_id", "control_mode", "updated_at"],
        unique=False,
    )

    op.add_column(
        "chat_executions",
        sa.Column(
            "control_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_chat_execution_control_version",
        "chat_executions",
        "control_version >= 0",
    )

    op.create_table(
        "conversation_control_events",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("actor_admin_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_mode", sa.String(length=20), nullable=False),
        sa.Column("to_mode", sa.String(length=20), nullable=False),
        sa.Column("from_assigned_admin_id", sa.UUID(), nullable=True),
        sa.Column("to_assigned_admin_id", sa.UUID(), nullable=True),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "control_version > 0",
            name="ck_conversation_control_event_version",
        ),
        sa.CheckConstraint(
            "event_type IN ('paused', 'taken_over', 'reassigned', 'resumed', 'closed')",
            name="ck_conversation_control_event_type",
        ),
        sa.CheckConstraint(
            "from_mode IN ('automated', 'paused', 'human', 'closed')",
            name="ck_conversation_control_event_from_mode",
        ),
        sa.CheckConstraint(
            "to_mode IN ('automated', 'paused', 'human', 'closed')",
            name="ck_conversation_control_event_to_mode",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            name=op.f("fk_conversation_control_events_actor_admin_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profiles.id"],
            name=op.f("fk_conversation_control_events_agent_id_agent_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.id"],
            name=op.f(
                "fk_conversation_control_events_conversation_id_chat_conversations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_assigned_admin_id"],
            ["admin_users.id"],
            name=op.f(
                "fk_conversation_control_events_from_assigned_admin_id_admin_users"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_assigned_admin_id"],
            ["admin_users.id"],
            name=op.f(
                "fk_conversation_control_events_to_assigned_admin_id_admin_users"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_control_events")),
        sa.UniqueConstraint(
            "conversation_id",
            "control_version",
            name="uq_conversation_control_event_version",
        ),
    )
    op.create_index(
        op.f("ix_conversation_control_events_actor_admin_id"),
        "conversation_control_events",
        ["actor_admin_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_control_events_agent_id"),
        "conversation_control_events",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_control_events_conversation_id"),
        "conversation_control_events",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_control_event_conversation_created",
        "conversation_control_events",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_control_event_conversation_created",
        table_name="conversation_control_events",
    )
    op.drop_index(
        op.f("ix_conversation_control_events_conversation_id"),
        table_name="conversation_control_events",
    )
    op.drop_index(
        op.f("ix_conversation_control_events_agent_id"),
        table_name="conversation_control_events",
    )
    op.drop_index(
        op.f("ix_conversation_control_events_actor_admin_id"),
        table_name="conversation_control_events",
    )
    op.drop_table("conversation_control_events")

    op.drop_constraint(
        "ck_chat_execution_control_version",
        "chat_executions",
        type_="check",
    )
    op.drop_column("chat_executions", "control_version")

    op.drop_index(
        "ix_chat_conversation_agent_control_updated",
        table_name="chat_conversations",
    )
    op.drop_index(
        op.f("ix_chat_conversations_assigned_admin_id"),
        table_name="chat_conversations",
    )
    op.drop_constraint(
        "ck_chat_conversation_human_assignment",
        "chat_conversations",
        type_="check",
    )
    op.drop_constraint(
        "ck_chat_conversation_control_version",
        "chat_conversations",
        type_="check",
    )
    op.drop_constraint(
        "ck_chat_conversation_control_mode",
        "chat_conversations",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_chat_conversations_assigned_admin_id_admin_users"),
        "chat_conversations",
        type_="foreignkey",
    )
    op.drop_column("chat_conversations", "control_reason")
    op.drop_column("chat_conversations", "control_changed_at")
    op.drop_column("chat_conversations", "assigned_admin_id")
    op.drop_column("chat_conversations", "control_version")
    op.drop_column("chat_conversations", "control_mode")
