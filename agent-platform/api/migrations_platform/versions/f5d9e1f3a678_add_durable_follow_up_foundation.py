"""Add durable follow-up execution foundations.

Revision ID: f5d9e1f3a678
Revises: f4c8d0e2f567
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5d9e1f3a678"
down_revision: str | None = "f4c8d0e2f567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA256_HEX = "'^[0-9a-f]{64}$'"


def upgrade() -> None:
    _add_task_columns()
    _create_automation_policies()
    _create_task_events()
    _quarantine_legacy_work()
    _replace_task_constraints()


def downgrade() -> None:
    _block_lossy_downgrade()
    _restore_legacy_task_constraints()
    op.execute(
        sa.text(
            "UPDATE follow_up_tasks AS task SET "
            "status = event.from_status, "
            "state_version = event.state_version - 1, "
            "review_required_at = NULL, last_safe_code = NULL "
            "FROM follow_up_task_events AS event "
            "WHERE event.task_id = task.id "
            "AND event.event_type = 'legacy_quarantined'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE follow_up_tasks SET review_required_at = NULL, "
            "last_safe_code = NULL WHERE status = 'review_required'"
        )
    )
    op.drop_table("follow_up_task_events")
    op.drop_table("commercial_automation_policies")
    _drop_task_columns()


def _add_task_columns() -> None:
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("fifo_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("target_channel", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "executed_consent_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "quote_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "chat_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "outbound_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("scheduled_control_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("scheduled_automation_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("scheduled_policy_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("executed_policy_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("last_safe_code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "follow_up_tasks",
        sa.Column("review_required_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("UPDATE follow_up_tasks SET available_at = due_at"))
    op.alter_column(
        "follow_up_tasks",
        "available_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_follow_up_task_conversation",
        "follow_up_tasks",
        "chat_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_follow_up_task_executed_consent",
        "follow_up_tasks",
        "consent_records",
        ["executed_consent_record_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_follow_up_task_quote_version",
        "follow_up_tasks",
        "quote_versions",
        ["quote_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_follow_up_task_chat_message",
        "follow_up_tasks",
        "chat_messages",
        ["chat_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_follow_up_task_outbound_message",
        "follow_up_tasks",
        "outbound_messages",
        ["outbound_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_follow_up_tasks_conversation_id",
        "follow_up_tasks",
        ["conversation_id"],
    )
    op.create_unique_constraint(
        "uq_follow_up_task_chat_message",
        "follow_up_tasks",
        ["chat_message_id"],
    )
    op.create_unique_constraint(
        "uq_follow_up_task_outbound_message",
        "follow_up_tasks",
        ["outbound_message_id"],
    )


def _create_automation_policies() -> None:
    op.create_table(
        "commercial_automation_policies",
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "allowed_kinds",
            postgresql.ARRAY(sa.String(length=30)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="UTC",
            nullable=False,
        ),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column(
            "min_interval_seconds",
            sa.Integer(),
            server_default="3600",
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column(
            "max_daily_tasks",
            sa.Integer(),
            server_default="25",
            nullable=False,
        ),
        sa.Column(
            "max_pending_tasks",
            sa.Integer(),
            server_default="100",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
            "allowed_kinds <@ ARRAY['commercial_follow_up', "
            "'meeting_coordination', 'proposal_reminder']::varchar[]",
            name="ck_commercial_automation_policy_allowed_kinds",
        ),
        sa.CheckConstraint(
            "char_length(btrim(timezone)) > 0",
            name="ck_commercial_automation_policy_timezone",
        ),
        sa.CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="ck_commercial_automation_policy_quiet_pair",
        ),
        sa.CheckConstraint(
            "quiet_hours_start IS NULL OR quiet_hours_start <> quiet_hours_end",
            name="ck_commercial_automation_policy_quiet_range",
        ),
        sa.CheckConstraint(
            "min_interval_seconds >= 0 AND max_attempts > 0 "
            "AND max_daily_tasks > 0 AND max_pending_tasks > 0",
            name="ck_commercial_automation_policy_limits",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_commercial_automation_policy_version",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_admin_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            name="uq_commercial_automation_policy_agent",
        ),
    )
    op.create_index(
        "ix_commercial_automation_policies_agent_id",
        "commercial_automation_policies",
        ["agent_id"],
    )
    op.execute(
        sa.text(
            "INSERT INTO commercial_automation_policies (id, agent_id) "
            "SELECT md5(agent.id::text || '-commercial-automation-policy')::uuid, "
            "agent.id FROM agent_profiles AS agent"
        )
    )


def _create_task_events() -> None:
    status_values = (
        "'scheduled', 'dispatch_queued', 'in_progress', 'completed', "
        "'cancelled', 'review_required'"
    )
    op.create_table(
        "follow_up_task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_worker_id", sa.String(length=120), nullable=True),
        sa.Column("routing_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "automation_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("target_channel", sa.String(length=40), nullable=True),
        sa.Column("control_version", sa.Integer(), nullable=True),
        sa.Column("automation_version", sa.Integer(), nullable=True),
        sa.Column("scheduled_policy_version", sa.Integer(), nullable=True),
        sa.Column("executed_policy_version", sa.Integer(), nullable=True),
        sa.Column(
            "consent_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "executed_consent_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("chat_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "outbound_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
            "event_type IN "
            "('scheduled', 'transitioned', 'deferred', 'legacy_quarantined')",
            name="ck_follow_up_task_event_type",
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({status_values})",
            name="ck_follow_up_task_event_from_status",
        ),
        sa.CheckConstraint(
            f"to_status IN ({status_values})",
            name="ck_follow_up_task_event_to_status",
        ),
        sa.CheckConstraint(
            "(event_type = 'scheduled' AND state_version = 0 "
            "AND from_status IS NULL AND to_status = 'scheduled') OR "
            "(event_type = 'transitioned' AND state_version > 0 "
            "AND from_status IS NOT NULL AND from_status <> to_status) OR "
            "(event_type = 'deferred' AND state_version > 0 "
            "AND from_status = 'scheduled' AND to_status = 'scheduled') OR "
            "(event_type = 'legacy_quarantined' AND state_version > 0 "
            "AND from_status IN ('scheduled', 'in_progress') "
            "AND to_status = 'review_required')",
            name="ck_follow_up_task_event_transition",
        ),
        sa.CheckConstraint(
            "actor_type IN ('agent', 'operator', 'worker', 'system', 'migration')",
            name="ck_follow_up_task_event_actor_type",
        ),
        sa.CheckConstraint(
            "(actor_type = 'agent' AND actor_agent_id IS NOT NULL "
            "AND actor_admin_id IS NULL AND actor_worker_id IS NULL) OR "
            "(actor_type = 'operator' AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NOT NULL AND actor_worker_id IS NULL) OR "
            "(actor_type = 'worker' AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NULL "
            "AND char_length(btrim(actor_worker_id)) > 0) OR "
            "(actor_type IN ('system', 'migration') AND actor_agent_id IS NULL "
            "AND actor_admin_id IS NULL AND actor_worker_id IS NULL)",
            name="ck_follow_up_task_event_actor",
        ),
        sa.CheckConstraint(
            "event_type = 'legacy_quarantined' OR "
            "safe_code = 'legacy_follow_up_context_unknown' OR "
            "(routing_agent_id IS NOT NULL AND automation_agent_id IS NOT NULL "
            "AND char_length(btrim(target_channel)) > 0 "
            "AND control_version IS NOT NULL AND automation_version IS NOT NULL "
            "AND scheduled_policy_version IS NOT NULL)",
            name="ck_follow_up_task_event_snapshot",
        ),
        sa.CheckConstraint(
            "control_version IS NULL OR control_version >= 0",
            name="ck_follow_up_task_event_control_version",
        ),
        sa.CheckConstraint(
            "automation_version IS NULL OR automation_version >= 0",
            name="ck_follow_up_task_event_automation_version",
        ),
        sa.CheckConstraint(
            "scheduled_policy_version IS NULL OR scheduled_policy_version >= 0",
            name="ck_follow_up_task_event_scheduled_policy_version",
        ),
        sa.CheckConstraint(
            "executed_policy_version IS NULL OR executed_policy_version >= 0",
            name="ck_follow_up_task_event_executed_policy_version",
        ),
        sa.CheckConstraint(
            "target_channel IS NULL OR target_channel ~ '^[a-z][a-z0-9_-]{0,39}$'",
            name="ck_follow_up_task_event_target_channel",
        ),
        sa.CheckConstraint(
            "safe_code IS NULL OR char_length(btrim(safe_code)) > 0",
            name="ck_follow_up_task_event_safe_code",
        ),
        sa.CheckConstraint(
            f"command_hash ~ {_SHA256_HEX}",
            name="ck_follow_up_task_event_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_follow_up_task_event_correlation",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_follow_up_task_event_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["follow_up_tasks.id"],
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
            ondelete="SET NULL",
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
            ["consent_record_id"],
            ["consent_records.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["executed_consent_record_id"],
            ["consent_records.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["outbound_message_id"],
            ["outbound_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "state_version",
            name="uq_follow_up_task_event_version",
        ),
        sa.UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_follow_up_task_event_idempotency",
        ),
        sa.UniqueConstraint(
            "chat_message_id",
            name="uq_follow_up_task_event_chat_message",
        ),
        sa.UniqueConstraint(
            "outbound_message_id",
            name="uq_follow_up_task_event_outbound_message",
        ),
    )
    op.create_index(
        "ix_follow_up_task_events_opportunity_id",
        "follow_up_task_events",
        ["opportunity_id"],
    )
    op.create_index(
        "ix_follow_up_task_event_task_created",
        "follow_up_task_events",
        ["task_id", "created_at"],
    )


def _quarantine_legacy_work() -> None:
    op.execute(
        sa.text(
            "UPDATE follow_up_tasks SET review_required_at = COALESCE(updated_at, now()), "
            "last_safe_code = 'legacy_follow_up_context_unknown' "
            "WHERE status = 'review_required'"
        )
    )
    op.execute(
        sa.text(
            "WITH legacy AS ("
            "SELECT id, opportunity_id, status AS from_status, state_version, "
            "consent_record_id FROM follow_up_tasks "
            "WHERE status IN ('scheduled', 'in_progress') FOR UPDATE"
            "), quarantined AS ("
            "UPDATE follow_up_tasks AS task SET status = 'review_required', "
            "state_version = legacy.state_version + 1, "
            "review_required_at = now(), "
            "last_safe_code = 'legacy_follow_up_context_unknown', "
            "lease_owner = NULL, lease_expires_at = NULL "
            "FROM legacy WHERE task.id = legacy.id "
            "RETURNING task.id, task.opportunity_id, task.state_version, "
            "task.consent_record_id"
            ") INSERT INTO follow_up_task_events ("
            "id, task_id, opportunity_id, event_type, from_status, to_status, "
            "state_version, actor_type, consent_record_id, safe_code, "
            "correlation_id, idempotency_key, command_hash"
            ") SELECT "
            "md5(quarantined.id::text || '-legacy-quarantined')::uuid, "
            "quarantined.id, quarantined.opportunity_id, 'legacy_quarantined', "
            "legacy.from_status, 'review_required', quarantined.state_version, "
            "'migration', quarantined.consent_record_id, "
            "'legacy_follow_up_context_unknown', "
            "'migration-f5d9e1f3a678', "
            "'legacy-quarantine-' || quarantined.id::text, "
            "md5(quarantined.id::text || '-legacy-quarantine-1') || "
            "md5(quarantined.id::text || '-legacy-quarantine-2') "
            "FROM quarantined JOIN legacy ON legacy.id = quarantined.id"
        )
    )


def _replace_task_constraints() -> None:
    for name in (
        "ck_follow_up_task_status",
        "ck_follow_up_task_state_version",
        "ck_follow_up_task_completed_at",
        "ck_follow_up_task_cancelled_at",
    ):
        op.drop_constraint(name, "follow_up_tasks", type_="check")
    op.drop_index("ix_follow_up_task_due", table_name="follow_up_tasks")
    op.create_check_constraint(
        "ck_follow_up_task_status",
        "follow_up_tasks",
        "status IN ('scheduled', 'dispatch_queued', 'in_progress', 'completed', "
        "'cancelled', 'review_required')",
    )
    op.create_check_constraint(
        "ck_follow_up_task_counters",
        "follow_up_tasks",
        "state_version >= 0 AND attempts >= 0 AND max_attempts > 0 "
        "AND attempts <= max_attempts",
    )
    op.create_check_constraint(
        "ck_follow_up_task_completed_at",
        "follow_up_tasks",
        "(status = 'completed') = (completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_cancelled_at",
        "follow_up_tasks",
        "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_review_required_at",
        "follow_up_tasks",
        "(status = 'review_required') = (review_required_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_review_safe_code",
        "follow_up_tasks",
        "status != 'review_required' OR char_length(btrim(last_safe_code)) > 0",
    )
    op.create_check_constraint(
        "ck_follow_up_task_lease_pair",
        "follow_up_tasks",
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_in_progress_lease",
        "follow_up_tasks",
        "(status = 'in_progress') = "
        "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_dispatch_snapshot",
        "follow_up_tasks",
        "status NOT IN ('scheduled', 'dispatch_queued', 'in_progress') OR "
        "(conversation_id IS NOT NULL AND char_length(btrim(fifo_key)) > 0 "
        "AND char_length(btrim(target_channel)) > 0 "
        "AND scheduled_control_version IS NOT NULL "
        "AND scheduled_automation_version IS NOT NULL "
        "AND scheduled_policy_version IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_control_version",
        "follow_up_tasks",
        "scheduled_control_version IS NULL OR scheduled_control_version >= 0",
    )
    op.create_check_constraint(
        "ck_follow_up_task_automation_version",
        "follow_up_tasks",
        "scheduled_automation_version IS NULL OR scheduled_automation_version >= 0",
    )
    op.create_check_constraint(
        "ck_follow_up_task_scheduled_policy_version",
        "follow_up_tasks",
        "scheduled_policy_version IS NULL OR scheduled_policy_version >= 0",
    )
    op.create_check_constraint(
        "ck_follow_up_task_executed_policy_version",
        "follow_up_tasks",
        "executed_policy_version IS NULL OR executed_policy_version >= 0",
    )
    op.create_check_constraint(
        "ck_follow_up_task_target_channel",
        "follow_up_tasks",
        "target_channel IS NULL OR target_channel ~ '^[a-z][a-z0-9_-]{0,39}$'",
    )
    op.create_check_constraint(
        "ck_follow_up_task_proposal_quote",
        "follow_up_tasks",
        "kind != 'proposal_reminder' OR quote_version_id IS NOT NULL OR "
        "status IN ('review_required', 'completed', 'cancelled')",
    )
    op.create_index(
        "ix_follow_up_task_claim",
        "follow_up_tasks",
        ["status", "available_at", "due_at"],
    )
    op.create_index(
        "ix_follow_up_task_fifo",
        "follow_up_tasks",
        ["fifo_key", "status", "available_at"],
    )
    op.create_index(
        "ix_follow_up_task_agent_status_due",
        "follow_up_tasks",
        ["assigned_agent_id", "status", "due_at"],
    )


def _block_lossy_downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM follow_up_task_events "
            "WHERE event_type <> 'legacy_quarantined') OR "
            "EXISTS (SELECT 1 FROM follow_up_tasks WHERE "
            "conversation_id IS NOT NULL OR chat_message_id IS NOT NULL OR "
            "outbound_message_id IS NOT NULL OR executed_consent_record_id IS NOT NULL "
            "OR scheduled_policy_version IS NOT NULL "
            "OR executed_policy_version IS NOT NULL "
            "OR quote_version_id IS NOT NULL OR status = 'dispatch_queued' "
            "OR attempts <> 0) OR "
            "EXISTS (SELECT 1 FROM commercial_automation_policies WHERE "
            "is_enabled OR cardinality(allowed_kinds) <> 0 OR version <> 0 "
            "OR timezone <> 'UTC' OR quiet_hours_start IS NOT NULL "
            "OR quiet_hours_end IS NOT NULL OR min_interval_seconds <> 3600 "
            "OR max_attempts <> 3 OR max_daily_tasks <> 25 "
            "OR max_pending_tasks <> 100 OR updated_by_admin_id IS NOT NULL) "
            "THEN RAISE EXCEPTION "
            "'durable follow-up evidence must be preserved before downgrade'; "
            "END IF; END $$"
        )
    )


def _restore_legacy_task_constraints() -> None:
    for name in (
        "ck_follow_up_task_status",
        "ck_follow_up_task_counters",
        "ck_follow_up_task_completed_at",
        "ck_follow_up_task_cancelled_at",
        "ck_follow_up_task_review_required_at",
        "ck_follow_up_task_review_safe_code",
        "ck_follow_up_task_lease_pair",
        "ck_follow_up_task_in_progress_lease",
        "ck_follow_up_task_dispatch_snapshot",
        "ck_follow_up_task_control_version",
        "ck_follow_up_task_automation_version",
        "ck_follow_up_task_scheduled_policy_version",
        "ck_follow_up_task_executed_policy_version",
        "ck_follow_up_task_target_channel",
        "ck_follow_up_task_proposal_quote",
    ):
        op.drop_constraint(name, "follow_up_tasks", type_="check")
    for name in (
        "ix_follow_up_task_claim",
        "ix_follow_up_task_fifo",
        "ix_follow_up_task_agent_status_due",
    ):
        op.drop_index(name, table_name="follow_up_tasks")
    op.create_check_constraint(
        "ck_follow_up_task_status",
        "follow_up_tasks",
        "status IN ('scheduled', 'in_progress', 'completed', 'cancelled', "
        "'review_required')",
    )
    op.create_check_constraint(
        "ck_follow_up_task_state_version",
        "follow_up_tasks",
        "state_version >= 0",
    )
    op.create_check_constraint(
        "ck_follow_up_task_completed_at",
        "follow_up_tasks",
        "(status = 'completed') = (completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_follow_up_task_cancelled_at",
        "follow_up_tasks",
        "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
    )
    op.create_index(
        "ix_follow_up_task_due",
        "follow_up_tasks",
        ["assigned_agent_id", "status", "due_at"],
    )


def _drop_task_columns() -> None:
    op.drop_constraint(
        "uq_follow_up_task_outbound_message",
        "follow_up_tasks",
        type_="unique",
    )
    op.drop_constraint(
        "uq_follow_up_task_chat_message",
        "follow_up_tasks",
        type_="unique",
    )
    op.drop_index(
        "ix_follow_up_tasks_conversation_id",
        table_name="follow_up_tasks",
    )
    for name in (
        "fk_follow_up_task_outbound_message",
        "fk_follow_up_task_chat_message",
        "fk_follow_up_task_quote_version",
        "fk_follow_up_task_executed_consent",
        "fk_follow_up_task_conversation",
    ):
        op.drop_constraint(name, "follow_up_tasks", type_="foreignkey")
    for column in (
        "review_required_at",
        "last_safe_code",
        "lease_expires_at",
        "lease_owner",
        "max_attempts",
        "attempts",
        "available_at",
        "executed_policy_version",
        "scheduled_policy_version",
        "scheduled_automation_version",
        "scheduled_control_version",
        "outbound_message_id",
        "chat_message_id",
        "quote_version_id",
        "executed_consent_record_id",
        "fifo_key",
        "target_channel",
        "conversation_id",
    ):
        op.drop_column("follow_up_tasks", column)
