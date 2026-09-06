"""Snapshot acting-agent epochs on chat executions.

Revision ID: f3b7c9d1e456
Revises: f2a6b8c0d345
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3b7c9d1e456"
down_revision: str | None = "f2a6b8c0d345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_executions",
        sa.Column(
            "automation_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_executions",
        sa.Column("automation_version", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE chat_executions AS execution "
            "SET automation_agent_id = conversation.automation_agent_id, "
            "automation_version = conversation.automation_version "
            "FROM chat_conversations AS conversation "
            "WHERE conversation.id = execution.conversation_id "
            "AND (execution.automation_agent_id IS NULL "
            "OR execution.automation_version IS NULL)"
        )
    )
    op.alter_column(
        "chat_executions",
        "automation_agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "chat_executions",
        "automation_version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.create_foreign_key(
        "fk_chat_executions_automation_agent_id_agent_profiles",
        "chat_executions",
        "agent_profiles",
        ["automation_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_chat_execution_automation_version",
        "chat_executions",
        "automation_version >= 0",
    )
    op.create_index(
        "ix_chat_executions_automation_agent_id",
        "chat_executions",
        ["automation_agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM chat_executions AS execution
                    JOIN chat_conversations AS conversation
                      ON conversation.id = execution.conversation_id
                    WHERE execution.automation_agent_id
                              <> conversation.automation_agent_id
                       OR execution.automation_version
                              <> conversation.automation_version
                ) THEN
                    RAISE EXCEPTION
                        'chat execution automation snapshots must be preserved '
                        'before downgrade';
                END IF;
            END
            $$
            """
        )
    )
    op.drop_index(
        "ix_chat_executions_automation_agent_id",
        table_name="chat_executions",
    )
    op.drop_constraint(
        "ck_chat_execution_automation_version",
        "chat_executions",
        type_="check",
    )
    op.drop_constraint(
        "fk_chat_executions_automation_agent_id_agent_profiles",
        "chat_executions",
        type_="foreignkey",
    )
    op.drop_column("chat_executions", "automation_version")
    op.drop_column("chat_executions", "automation_agent_id")
