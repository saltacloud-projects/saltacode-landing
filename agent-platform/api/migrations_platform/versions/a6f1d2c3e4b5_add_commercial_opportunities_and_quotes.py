"""Add commercial opportunities, follow-ups, and authoritative quotes.

Revision ID: a6f1d2c3e4b5
Revises: 4c91b2f7e6a0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6f1d2c3e4b5"
down_revision: str | None = "4c91b2f7e6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = (
    "'new', 'qualified', 'proposal_requested', 'proposal_preparing', "
    "'proposal_sent', 'negotiation', 'meeting_scheduled', 'won', 'lost', "
    "'paused'"
)
_SHA256_HEX = "'^[0-9a-f]{64}$'"


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("created_by_agent_id", sa.UUID(), nullable=False),
        sa.Column("assigned_agent_id", sa.UUID(), nullable=False),
        sa.Column("assigned_operator_id", sa.UUID(), nullable=True),
        sa.Column(
            "stage",
            sa.String(length=30),
            server_default=sa.text("'new'"),
            nullable=False,
        ),
        sa.Column(
            "control_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            f"stage IN ({_STAGES})",
            name="ck_opportunity_stage",
        ),
        sa.CheckConstraint(
            "control_version >= 0",
            name="ck_opportunity_control_version",
        ),
        sa.CheckConstraint(
            "char_length(btrim(title)) > 0",
            name="ck_opportunity_title",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_opportunity_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_idempotency",
        ),
        sa.CheckConstraint(
            "(stage IN ('won', 'lost')) = (closed_at IS NOT NULL)",
            name="ck_opportunity_closed_at",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"],
            ["agent_profiles.id"],
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
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_by_agent_id",
            "idempotency_key",
            name="uq_opportunity_creator_idempotency",
        ),
    )
    for column in (
        "contact_id",
        "created_by_agent_id",
        "assigned_agent_id",
        "assigned_operator_id",
    ):
        op.create_index(
            op.f(f"ix_opportunities_{column}"),
            "opportunities",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_opportunity_assignee_stage_updated",
        "opportunities",
        ["assigned_agent_id", "stage", "updated_at"],
        unique=False,
    )

    op.create_table(
        "opportunity_stage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("assigned_agent_id", sa.UUID(), nullable=False),
        sa.Column("actor_operator_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("from_stage", sa.String(length=30), nullable=True),
        sa.Column("to_stage", sa.String(length=30), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
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
            "event_type IN ('created', 'stage_changed')",
            name="ck_opportunity_stage_event_type",
        ),
        sa.CheckConstraint(
            f"from_stage IS NULL OR from_stage IN ({_STAGES})",
            name="ck_opportunity_stage_event_from",
        ),
        sa.CheckConstraint(
            f"to_stage IN ({_STAGES})",
            name="ck_opportunity_stage_event_to",
        ),
        sa.CheckConstraint(
            "(event_type = 'created' AND control_version = 0 AND "
            "from_stage IS NULL AND to_stage = 'new') OR "
            "(event_type = 'stage_changed' AND control_version > 0 AND "
            "from_stage IS NOT NULL AND from_stage <> to_stage)",
            name="ck_opportunity_stage_event_shape",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_opportunity_stage_event_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_stage_event_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_stage_event_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_operator_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "control_version",
            name="uq_opportunity_stage_event_version",
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_stage_event_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_opportunity_stage_events_opportunity_id"),
        "opportunity_stage_events",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_stage_events_assigned_agent_id"),
        "opportunity_stage_events",
        ["assigned_agent_id"],
        unique=False,
    )

    op.create_table(
        "opportunity_ownership_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("actor_agent_id", sa.UUID(), nullable=False),
        sa.Column("actor_operator_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("from_agent_id", sa.UUID(), nullable=True),
        sa.Column("to_agent_id", sa.UUID(), nullable=False),
        sa.Column("from_operator_id", sa.UUID(), nullable=True),
        sa.Column("to_operator_id", sa.UUID(), nullable=True),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
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
            "event_type IN ('created', 'reassigned')",
            name="ck_opportunity_ownership_event_type",
        ),
        sa.CheckConstraint(
            "(event_type = 'created' AND control_version = 0 AND "
            "from_agent_id IS NULL) OR "
            "(event_type = 'reassigned' AND control_version > 0 AND "
            "from_agent_id IS NOT NULL AND "
            "(from_agent_id <> to_agent_id OR "
            "from_operator_id IS DISTINCT FROM to_operator_id))",
            name="ck_opportunity_ownership_event_shape",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_opportunity_ownership_event_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_ownership_event_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_ownership_event_idempotency",
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
            ["actor_operator_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_operator_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_operator_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "control_version",
            name="uq_opportunity_ownership_event_version",
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_ownership_event_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_opportunity_ownership_events_opportunity_id"),
        "opportunity_ownership_events",
        ["opportunity_id"],
        unique=False,
    )

    op.create_table(
        "opportunity_conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("linked_by_agent_id", sa.UUID(), nullable=False),
        sa.Column("linked_by_operator_id", sa.UUID(), nullable=True),
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
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_opportunity_conversation_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_opportunity_conversation_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_opportunity_conversation_idempotency",
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
            ["linked_by_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_operator_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "conversation_id",
            name="uq_opportunity_conversation_link",
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_conversation_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_opportunity_conversations_opportunity_id"),
        "opportunity_conversations",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_conversations_conversation_id"),
        "opportunity_conversations",
        ["conversation_id"],
        unique=False,
    )

    op.create_table(
        "follow_up_tasks",
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("contact_point_id", sa.UUID(), nullable=True),
        sa.Column("consent_record_id", sa.UUID(), nullable=False),
        sa.Column("assigned_agent_id", sa.UUID(), nullable=False),
        sa.Column("assigned_operator_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'scheduled'"),
            nullable=False,
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "kind IN ('commercial_follow_up', 'meeting_coordination', "
            "'proposal_reminder')",
            name="ck_follow_up_task_kind",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'in_progress', 'completed', 'cancelled', "
            "'review_required')",
            name="ck_follow_up_task_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_follow_up_task_state_version",
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_follow_up_task_completed_at",
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_follow_up_task_cancelled_at",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_follow_up_task_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_follow_up_task_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_follow_up_task_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contact_point_id"],
            ["contact_points.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["consent_record_id"],
            ["consent_records.id"],
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
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_follow_up_task_idempotency",
        ),
    )
    for column in (
        "opportunity_id",
        "contact_point_id",
        "consent_record_id",
        "assigned_agent_id",
    ):
        op.create_index(
            op.f(f"ix_follow_up_tasks_{column}"),
            "follow_up_tasks",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_follow_up_task_due",
        "follow_up_tasks",
        ["assigned_agent_id", "status", "due_at"],
        unique=False,
    )

    op.create_table(
        "quote_requests",
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_agent_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_operator_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'unavailable'"),
            nullable=False,
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "requirements_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('unavailable', 'review_required', 'issued', 'cancelled')",
            name="ck_quote_request_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_quote_request_state_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requirements_json) = 'object'",
            name="ck_quote_request_requirements_object",
        ),
        sa.CheckConstraint(
            "status NOT IN ('unavailable', 'review_required') OR "
            "failure_code IS NOT NULL",
            name="ck_quote_request_failure_reason",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_quote_request_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_quote_request_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_quote_request_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_operator_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_quote_request_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_quote_requests_opportunity_id"),
        "quote_requests",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quote_requests_requested_by_agent_id"),
        "quote_requests",
        ["requested_by_agent_id"],
        unique=False,
    )

    op.create_table(
        "quote_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("quote_request_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("authority_name", sa.String(length=120), nullable=False),
        sa.Column("authority_version", sa.String(length=80), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_quote_version_number"),
        sa.CheckConstraint("status = 'issued'", name="ck_quote_version_status"),
        sa.CheckConstraint(
            "char_length(btrim(authority_name)) > 0 AND "
            "char_length(btrim(authority_version)) > 0 AND "
            "char_length(btrim(external_reference)) > 0 AND "
            "issued_at IS NOT NULL",
            name="ck_quote_version_authority_evidence",
        ),
        sa.CheckConstraint(
            f"content_hash ~ {_SHA256_HEX}",
            name="ck_quote_version_content_hash",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_quote_version_command_hash",
        ),
        sa.CheckConstraint(
            "issued_at <= created_at",
            name="ck_quote_version_issued_before_recorded",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_quote_version_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_quote_version_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["quote_request_id"],
            ["quote_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quote_request_id",
            "version",
            name="uq_quote_version_request_version",
        ),
        sa.UniqueConstraint(
            "quote_request_id",
            "idempotency_key",
            name="uq_quote_version_request_idempotency",
        ),
        sa.UniqueConstraint(
            "authority_name",
            "external_reference",
            name="uq_quote_version_authority_reference",
        ),
    )
    op.create_index(
        op.f("ix_quote_versions_quote_request_id"),
        "quote_versions",
        ["quote_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_quote_versions_quote_request_id"),
        table_name="quote_versions",
    )
    op.drop_table("quote_versions")

    op.drop_index(
        op.f("ix_quote_requests_requested_by_agent_id"),
        table_name="quote_requests",
    )
    op.drop_index(
        op.f("ix_quote_requests_opportunity_id"),
        table_name="quote_requests",
    )
    op.drop_table("quote_requests")

    op.drop_index("ix_follow_up_task_due", table_name="follow_up_tasks")
    for column in (
        "assigned_agent_id",
        "consent_record_id",
        "contact_point_id",
        "opportunity_id",
    ):
        op.drop_index(
            op.f(f"ix_follow_up_tasks_{column}"),
            table_name="follow_up_tasks",
        )
    op.drop_table("follow_up_tasks")

    op.drop_index(
        op.f("ix_opportunity_conversations_conversation_id"),
        table_name="opportunity_conversations",
    )
    op.drop_index(
        op.f("ix_opportunity_conversations_opportunity_id"),
        table_name="opportunity_conversations",
    )
    op.drop_table("opportunity_conversations")

    op.drop_index(
        op.f("ix_opportunity_ownership_events_opportunity_id"),
        table_name="opportunity_ownership_events",
    )
    op.drop_table("opportunity_ownership_events")

    op.drop_index(
        op.f("ix_opportunity_stage_events_assigned_agent_id"),
        table_name="opportunity_stage_events",
    )
    op.drop_index(
        op.f("ix_opportunity_stage_events_opportunity_id"),
        table_name="opportunity_stage_events",
    )
    op.drop_table("opportunity_stage_events")

    op.drop_index(
        "ix_opportunity_assignee_stage_updated",
        table_name="opportunities",
    )
    for column in (
        "assigned_operator_id",
        "assigned_agent_id",
        "created_by_agent_id",
        "contact_id",
    ):
        op.drop_index(
            op.f(f"ix_opportunities_{column}"),
            table_name="opportunities",
        )
    op.drop_table("opportunities")
