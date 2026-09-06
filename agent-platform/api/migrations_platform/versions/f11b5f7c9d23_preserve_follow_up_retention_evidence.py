"""Preserve follow-up evidence across conversation retention.

Revision ID: f11b5f7c9d23
Revises: f10a4e6b8c12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f11b5f7c9d23"
down_revision: str | None = "f10a4e6b8c12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("follow_up_tasks", "follow_up_task_events"):
        op.add_column(
            table_name,
            sa.Column(
                "source_conversation_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "had_chat_message_evidence",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "had_outbound_message_evidence",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )

    op.execute(
        "UPDATE follow_up_tasks SET "
        "source_conversation_id = conversation_id, "
        "had_chat_message_evidence = (chat_message_id IS NOT NULL), "
        "had_outbound_message_evidence = (outbound_message_id IS NOT NULL)"
    )
    op.execute(
        "UPDATE follow_up_task_events AS event SET "
        "source_conversation_id = task.conversation_id, "
        "had_chat_message_evidence = (event.chat_message_id IS NOT NULL), "
        "had_outbound_message_evidence = (event.outbound_message_id IS NOT NULL) "
        "FROM follow_up_tasks AS task WHERE task.id = event.task_id"
    )
    op.create_index(
        "ix_follow_up_tasks_source_conversation_id",
        "follow_up_tasks",
        ["source_conversation_id"],
    )
    op.create_index(
        "ix_follow_up_task_events_source_conversation_id",
        "follow_up_task_events",
        ["source_conversation_id"],
    )


def downgrade() -> None:
    _block_historical_evidence_loss()
    op.drop_index(
        "ix_follow_up_task_events_source_conversation_id",
        table_name="follow_up_task_events",
    )
    op.drop_index(
        "ix_follow_up_tasks_source_conversation_id",
        table_name="follow_up_tasks",
    )
    for table_name in ("follow_up_task_events", "follow_up_tasks"):
        op.drop_column(table_name, "had_outbound_message_evidence")
        op.drop_column(table_name, "had_chat_message_evidence")
        op.drop_column(table_name, "source_conversation_id")


def _block_historical_evidence_loss() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM follow_up_tasks
                    WHERE conversation_id IS NULL
                      AND (
                        source_conversation_id IS NOT NULL
                        OR had_chat_message_evidence
                        OR had_outbound_message_evidence
                      )
                ) OR EXISTS (
                    SELECT 1
                    FROM follow_up_task_events AS event
                    JOIN follow_up_tasks AS task ON task.id = event.task_id
                    WHERE (
                        event.source_conversation_id IS NOT NULL
                        AND event.source_conversation_id IS DISTINCT FROM task.conversation_id
                    ) OR (
                        event.had_chat_message_evidence
                        AND event.chat_message_id IS NULL
                    ) OR (
                        event.had_outbound_message_evidence
                        AND event.outbound_message_id IS NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'follow-up retention evidence must be preserved; '
                        'operator must archive or migrate it before downgrade';
                END IF;
            END
            $$;
            """
        )
    )
