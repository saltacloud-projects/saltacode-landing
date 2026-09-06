"""Add versioned conversation automation assignments.

Revision ID: f2a6b8c0d345
Revises: e1f5a7b9c234
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a6b8c0d345"
down_revision: str | None = "e1f5a7b9c234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA256_HEX = "'^[0-9a-f]{64}$'"


def upgrade() -> None:
    op.add_column(
        "chat_conversations",
        sa.Column(
            "automation_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_conversations",
        sa.Column("automation_version", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE chat_conversations "
            "SET automation_agent_id = agent_id, automation_version = 0 "
            "WHERE automation_agent_id IS NULL OR automation_version IS NULL"
        )
    )
    op.alter_column(
        "chat_conversations",
        "automation_agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "chat_conversations",
        "automation_version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.create_foreign_key(
        "fk_chat_conversations_automation_agent_id_agent_profiles",
        "chat_conversations",
        "agent_profiles",
        ["automation_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_chat_conversation_automation_version",
        "chat_conversations",
        "automation_version >= 0",
    )
    op.create_index(
        "ix_chat_conversations_automation_agent_id",
        "chat_conversations",
        ["automation_agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_conversation_automation_status_updated",
        "chat_conversations",
        ["automation_agent_id", "status", "updated_at"],
        unique=False,
    )

    op.create_table(
        "conversation_automation_assignment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "routing_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "from_automation_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "to_automation_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("automation_version", sa.Integer(), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.String(length=80), nullable=False),
        sa.Column(
            "opportunity_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "actor_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "actor_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "automation_version >= 0",
            name="ck_conversation_automation_assignment_version",
        ),
        sa.CheckConstraint(
            "((applied AND from_automation_agent_id <> to_automation_agent_id "
            "AND automation_version > 0) OR "
            "(NOT applied AND "
            "from_automation_agent_id = to_automation_agent_id))",
            name="ck_conversation_automation_assignment_shape",
        ),
        sa.CheckConstraint(
            "((actor_agent_id IS NOT NULL AND actor_admin_id IS NULL) OR "
            "(actor_agent_id IS NULL AND actor_admin_id IS NOT NULL))",
            name="ck_conversation_automation_assignment_actor",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_conversation_automation_assignment_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(trigger)) > 0",
            name="ck_conversation_automation_assignment_trigger",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_conversation_automation_assignment_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_conversation_automation_assignment_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["routing_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_automation_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_automation_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_conversation_automation_assignment_idempotency",
        ),
    )
    for column in (
        "actor_admin_id",
        "actor_agent_id",
        "conversation_id",
        "opportunity_id",
        "routing_agent_id",
    ):
        op.create_index(
            f"ix_conversation_automation_assignment_events_{column}",
            "conversation_automation_assignment_events",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_conversation_automation_event_target_agent",
        "conversation_automation_assignment_events",
        ["to_automation_agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_automation_assignment_conversation_created",
        "conversation_automation_assignment_events",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_conversation_automation_assignment_applied_version",
        "conversation_automation_assignment_events",
        ["conversation_id", "automation_version"],
        unique=True,
        postgresql_where=sa.text("applied"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM conversation_automation_assignment_events
                ) OR EXISTS (
                    SELECT 1
                    FROM chat_conversations
                    WHERE automation_agent_id <> agent_id
                       OR automation_version <> 0
                ) THEN
                    RAISE EXCEPTION
                        'automation assignment history must be preserved before downgrade';
                END IF;
            END
            $$
            """
        )
    )
    op.drop_index(
        "uq_conversation_automation_assignment_applied_version",
        table_name="conversation_automation_assignment_events",
    )
    op.drop_index(
        "ix_conversation_automation_assignment_conversation_created",
        table_name="conversation_automation_assignment_events",
    )
    op.drop_index(
        "ix_conversation_automation_event_target_agent",
        table_name="conversation_automation_assignment_events",
    )
    for column in reversed(
        (
            "actor_admin_id",
            "actor_agent_id",
            "conversation_id",
            "opportunity_id",
            "routing_agent_id",
        )
    ):
        op.drop_index(
            f"ix_conversation_automation_assignment_events_{column}",
            table_name="conversation_automation_assignment_events",
        )
    op.drop_table("conversation_automation_assignment_events")

    op.drop_index(
        "ix_chat_conversation_automation_status_updated",
        table_name="chat_conversations",
    )
    op.drop_index(
        "ix_chat_conversations_automation_agent_id",
        table_name="chat_conversations",
    )
    op.drop_constraint(
        "ck_chat_conversation_automation_version",
        "chat_conversations",
        type_="check",
    )
    op.drop_constraint(
        "fk_chat_conversations_automation_agent_id_agent_profiles",
        "chat_conversations",
        type_="foreignkey",
    )
    op.drop_column("chat_conversations", "automation_version")
    op.drop_column("chat_conversations", "automation_agent_id")
