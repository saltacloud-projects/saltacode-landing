"""Add the auditable meeting aggregate.

Revision ID: f10a4e6b8c12
Revises: f9d3e5a7b012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f10a4e6b8c12"
down_revision: str | None = "f9d3e5a7b012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_meetings()
    _create_meeting_slots()
    op.create_foreign_key(
        "fk_meeting_selected_slot",
        "meetings",
        "meeting_slots",
        ["selected_slot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _create_meeting_events()


def downgrade() -> None:
    _block_evidence_loss()
    op.drop_table("meeting_events")
    op.drop_constraint(
        "fk_meeting_selected_slot",
        "meetings",
        type_="foreignkey",
    )
    op.drop_table("meeting_slots")
    op.drop_table("meetings")


def _create_meetings() -> None:
    op.create_table(
        "meetings",
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_under_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_by_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="requested",
            nullable=False,
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "proposal_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "selected_slot_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
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
            "status IN ('requested', 'slots_proposed', 'awaiting_response', "
            "'slot_selected', 'calendar_pending', 'scheduled', "
            "'reschedule_requested', 'cancelled', 'review_required')",
            name="ck_meeting_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_meeting_state_version",
        ),
        sa.CheckConstraint(
            "proposal_version >= 0",
            name="ck_meeting_proposal_version",
        ),
        sa.CheckConstraint(
            "((created_by_agent_id IS NOT NULL AND created_by_admin_id IS NULL) "
            "OR (created_by_agent_id IS NULL AND created_by_admin_id IS NOT NULL))",
            name="ck_meeting_creator",
        ),
        sa.CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_meeting_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_meeting_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_meeting_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_under_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_under_agent_id",
            "idempotency_key",
            name="uq_meeting_agent_idempotency",
        ),
    )
    op.create_index(
        "ix_meeting_opportunity_status_updated",
        "meetings",
        ["opportunity_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_meetings_conversation_id",
        "meetings",
        ["conversation_id"],
    )
    op.create_index(
        "ix_meetings_created_under_agent_id",
        "meetings",
        ["created_under_agent_id"],
    )
    op.create_index(
        "ix_meetings_opportunity_id",
        "meetings",
        ["opportunity_id"],
    )


def _create_meeting_slots() -> None:
    op.create_table(
        "meeting_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "proposal_version > 0",
            name="ck_meeting_slot_proposal",
        ),
        sa.CheckConstraint("position > 0", name="ck_meeting_slot_position"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_meeting_slot_range"),
        sa.CheckConstraint(
            "char_length(btrim(timezone)) > 0",
            name="ck_meeting_slot_timezone",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id",
            "proposal_version",
            "position",
            name="uq_meeting_slot_proposal_position",
        ),
    )
    op.create_index(
        "ix_meeting_slot_meeting_proposal",
        "meeting_slots",
        ["meeting_id", "proposal_version"],
    )


def _create_meeting_events() -> None:
    op.create_table(
        "meeting_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assigned_operator_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("routing_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("automation_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("opportunity_control_version", sa.Integer(), nullable=False),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_control_version", sa.Integer(), nullable=True),
        sa.Column("conversation_automation_version", sa.Integer(), nullable=True),
        sa.Column("source_channel", sa.String(length=30), nullable=True),
        sa.Column("evidence_type", sa.String(length=40), nullable=True),
        sa.Column("evidence_reference", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("safe_code", sa.String(length=80), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'slots_proposed', 'awaiting_response', "
            "'slot_selected', 'scheduled_manual', 'reschedule_requested', "
            "'cancelled', 'review_required')",
            name="ck_meeting_event_type",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('requested', "
            "'slots_proposed', 'awaiting_response', 'slot_selected', "
            "'calendar_pending', 'scheduled', 'reschedule_requested', "
            "'cancelled', 'review_required')",
            name="ck_meeting_event_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('requested', 'slots_proposed', 'awaiting_response', "
            "'slot_selected', 'calendar_pending', 'scheduled', "
            "'reschedule_requested', 'cancelled', 'review_required')",
            name="ck_meeting_event_to_status",
        ),
        sa.CheckConstraint(
            "(event_type = 'created' AND state_version = 0 AND "
            "from_status IS NULL AND to_status = 'requested') OR "
            "(event_type <> 'created' AND state_version > 0 AND "
            "from_status IS NOT NULL)",
            name="ck_meeting_event_shape",
        ),
        sa.CheckConstraint(
            "proposal_version >= 0",
            name="ck_meeting_event_proposal_version",
        ),
        sa.CheckConstraint(
            "opportunity_control_version >= 0",
            name="ck_meeting_event_opportunity_version",
        ),
        sa.CheckConstraint(
            "actor_type IN ('agent', 'operator')",
            name="ck_meeting_event_actor_type",
        ),
        sa.CheckConstraint(
            "((actor_type = 'agent' AND actor_agent_id IS NOT NULL "
            "AND actor_admin_id IS NULL) OR "
            "(actor_type = 'operator' AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NOT NULL))",
            name="ck_meeting_event_actor",
        ),
        sa.CheckConstraint(
            "((routing_agent_id IS NULL AND automation_agent_id IS NULL "
            "AND conversation_control_version IS NULL "
            "AND conversation_automation_version IS NULL "
            "AND source_channel IS NULL) OR "
            "(routing_agent_id IS NOT NULL AND automation_agent_id IS NOT NULL "
            "AND conversation_control_version IS NOT NULL "
            "AND conversation_automation_version IS NOT NULL "
            "AND source_channel IS NOT NULL))",
            name="ck_meeting_event_conversation_snapshot",
        ),
        sa.CheckConstraint(
            "conversation_control_version IS NULL OR conversation_control_version >= 0",
            name="ck_meeting_event_control_version",
        ),
        sa.CheckConstraint(
            "conversation_automation_version IS NULL OR "
            "conversation_automation_version >= 0",
            name="ck_meeting_event_automation_version",
        ),
        sa.CheckConstraint(
            "event_type <> 'scheduled_manual' OR "
            "(actor_type = 'operator' AND evidence_type IS NOT NULL "
            "AND evidence_reference IS NOT NULL AND slot_id IS NOT NULL)",
            name="ck_meeting_event_manual_evidence",
        ),
        sa.CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_meeting_event_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_meeting_event_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_meeting_event_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.id"],
            ondelete="SET NULL",
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
        sa.ForeignKeyConstraint(
            ["assigned_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_operator_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["routing_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["automation_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"],
            ["meeting_slots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id",
            "state_version",
            name="uq_meeting_event_state_version",
        ),
        sa.UniqueConstraint(
            "meeting_id",
            "idempotency_key",
            name="uq_meeting_event_idempotency",
        ),
    )
    op.create_index(
        "ix_meeting_event_opportunity_created",
        "meeting_events",
        ["opportunity_id", "created_at"],
    )
    op.create_index(
        "ix_meeting_events_meeting_id",
        "meeting_events",
        ["meeting_id"],
    )
    op.create_index(
        "ix_meeting_events_opportunity_id",
        "meeting_events",
        ["opportunity_id"],
    )


def _block_evidence_loss() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM meetings) "
            "OR EXISTS (SELECT 1 FROM meeting_slots) "
            "OR EXISTS (SELECT 1 FROM meeting_events) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade: meeting evidence must be preserved'; "
            "END IF; END $$"
        )
    )
