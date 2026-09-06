"""Snapshot acting-agent epochs on automated outbound commands.

Revision ID: f4c8d0e2f567
Revises: f3b7c9d1e456
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4c8d0e2f567"
down_revision: str | None = "f3b7c9d1e456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column(
            "automation_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "outbound_messages",
        sa.Column("automation_version", sa.Integer(), nullable=True),
    )

    # Version zero proves that no acting-agent reassignment has occurred, so
    # the current conversation snapshot is safe evidence for legacy commands.
    op.execute(
        sa.text(
            "UPDATE outbound_messages AS message "
            "SET automation_agent_id = conversation.automation_agent_id, "
            "automation_version = 0 "
            "FROM chat_conversations AS conversation "
            "WHERE message.conversation_id = conversation.id "
            "AND message.sender_type IN ('automation', 'system') "
            "AND conversation.automation_version = 0"
        )
    )

    # A queued command from an older, unknown acting epoch must never be sent.
    op.execute(
        sa.text(
            "WITH cancelled AS ("
            "UPDATE outbound_messages AS message "
            "SET status = 'cancelled', locked_by = NULL, locked_at = NULL "
            "FROM chat_conversations AS conversation "
            "WHERE message.conversation_id = conversation.id "
            "AND message.sender_type IN ('automation', 'system') "
            "AND message.automation_agent_id IS NULL "
            "AND message.status = 'queued' "
            "RETURNING message.id"
            ") "
            "INSERT INTO outbound_delivery_events "
            "(id, outbound_message_id, attempt_id, event_type, from_status, "
            "to_status, actor_type, actor_id, safe_code, created_at) "
            "SELECT gen_random_uuid(), id, NULL, 'cancelled', 'queued', "
            "'cancelled', 'system', NULL, 'legacy_automation_unknown', now() "
            "FROM cancelled"
        )
    )

    # A legacy dispatch in flight has uncertain provider acceptance and remains
    # fail-closed for explicit manual review rather than being retried.
    op.execute(
        sa.text(
            "WITH uncertain AS ("
            "UPDATE outbound_messages AS message "
            "SET status = 'delivery_unknown', locked_by = NULL, locked_at = NULL "
            "WHERE message.sender_type IN ('automation', 'system') "
            "AND message.automation_agent_id IS NULL "
            "AND message.status = 'dispatching' "
            "RETURNING message.id"
            ") "
            "INSERT INTO outbound_delivery_events "
            "(id, outbound_message_id, attempt_id, event_type, from_status, "
            "to_status, actor_type, actor_id, safe_code, created_at) "
            "SELECT gen_random_uuid(), id, NULL, 'delivery_unknown', "
            "'dispatching', 'delivery_unknown', 'system', NULL, "
            "'legacy_automation_unknown', now() FROM uncertain"
        )
    )

    op.drop_constraint(
        "ck_outbound_message_counters",
        "outbound_messages",
        type_="check",
    )
    op.create_check_constraint(
        "ck_outbound_message_counters",
        "outbound_messages",
        "control_version >= 0 "
        "AND (automation_version IS NULL OR automation_version >= 0) "
        "AND sequence > 0 AND last_attempt_number >= 0",
    )
    op.create_check_constraint(
        "ck_outbound_message_automation_snapshot_pair",
        "outbound_messages",
        "(automation_agent_id IS NULL) = (automation_version IS NULL)",
    )
    op.create_foreign_key(
        "fk_outbound_messages_automation_agent_id_agent_profiles",
        "outbound_messages",
        "agent_profiles",
        ["automation_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_outbound_messages_automation_agent_id",
        "outbound_messages",
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
                    FROM outbound_messages AS message
                    JOIN chat_conversations AS conversation
                      ON conversation.id = message.conversation_id
                    WHERE message.automation_agent_id IS NOT NULL
                      AND (
                        message.automation_version <> 0
                        OR conversation.automation_version <> 0
                        OR message.automation_agent_id
                             <> conversation.automation_agent_id
                      )
                ) THEN
                    RAISE EXCEPTION
                        'outbound automation snapshots must be preserved '
                        'before downgrade';
                END IF;
            END
            $$
            """
        )
    )
    op.drop_index(
        "ix_outbound_messages_automation_agent_id",
        table_name="outbound_messages",
    )
    op.drop_constraint(
        "fk_outbound_messages_automation_agent_id_agent_profiles",
        "outbound_messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_outbound_message_automation_snapshot_pair",
        "outbound_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_outbound_message_counters",
        "outbound_messages",
        type_="check",
    )
    op.create_check_constraint(
        "ck_outbound_message_counters",
        "outbound_messages",
        "control_version >= 0 AND sequence > 0 AND last_attempt_number >= 0",
    )
    op.drop_column("outbound_messages", "automation_version")
    op.drop_column("outbound_messages", "automation_agent_id")
