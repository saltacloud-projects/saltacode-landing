"""Scope commercial follow-up consent to an explicit delivery target.

Revision ID: f6a0b2c4d789
Revises: f5d9e1f3a678
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a0b2c4d789"
down_revision: str | None = "f5d9e1f3a678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consent_records",
        sa.Column("target_channel", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "consent_records",
        sa.Column(
            "actor_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_consent_record_target_channel",
        "consent_records",
        "target_channel IS NULL OR target_channel ~ '^[a-z][a-z0-9_-]{0,39}$'",
    )
    op.create_foreign_key(
        "fk_consent_record_actor_admin",
        "consent_records",
        "admin_users",
        ["actor_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_consent_records_actor_admin_id",
        "consent_records",
        ["actor_admin_id"],
    )
    op.create_index(
        "ix_consent_record_target_effective",
        "consent_records",
        [
            "agent_id",
            "principal_id",
            "purpose",
            "source_conversation_id",
            "target_channel",
            "contact_point_id",
            "occurred_at",
        ],
    )
    op.add_column(
        "follow_up_task_events",
        sa.Column(
            "caused_by_consent_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_follow_up_event_caused_by_consent",
        "follow_up_task_events",
        "consent_records",
        ["caused_by_consent_record_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _quarantine_targetless_pending_work()


def downgrade() -> None:
    _block_lossy_downgrade()
    op.drop_constraint(
        "fk_follow_up_event_caused_by_consent",
        "follow_up_task_events",
        type_="foreignkey",
    )
    op.drop_column("follow_up_task_events", "caused_by_consent_record_id")
    op.drop_index(
        "ix_consent_record_target_effective",
        table_name="consent_records",
    )
    op.drop_index(
        "ix_consent_records_actor_admin_id",
        table_name="consent_records",
    )
    op.drop_constraint(
        "fk_consent_record_actor_admin",
        "consent_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_consent_record_target_channel",
        "consent_records",
        type_="check",
    )
    op.drop_column("consent_records", "actor_admin_id")
    op.drop_column("consent_records", "target_channel")


def _quarantine_targetless_pending_work() -> None:
    op.execute(
        sa.text(
            "WITH affected AS ("
            "SELECT task.id, task.opportunity_id, task.status AS from_status, "
            "task.state_version, task.assigned_agent_id, task.target_channel, "
            "task.scheduled_control_version, task.scheduled_automation_version, "
            "task.scheduled_policy_version, task.executed_policy_version, "
            "task.consent_record_id, task.executed_consent_record_id, "
            "task.chat_message_id, task.outbound_message_id, "
            "conversation.agent_id AS routing_agent_id "
            "FROM follow_up_tasks AS task "
            "JOIN consent_records AS consent ON consent.id = task.consent_record_id "
            "LEFT JOIN chat_conversations AS conversation "
            "ON conversation.id = task.conversation_id "
            "WHERE consent.purpose = 'commercial_follow_up' "
            "AND consent.target_channel IS NULL "
            "AND task.status IN ('scheduled', 'dispatch_queued', 'in_progress') "
            "FOR UPDATE OF task"
            "), quarantined AS ("
            "UPDATE follow_up_tasks AS task SET status = 'review_required', "
            "state_version = affected.state_version + 1, review_required_at = now(), "
            "last_safe_code = 'commercial_consent_target_unknown', "
            "lease_owner = NULL, lease_expires_at = NULL "
            "FROM affected WHERE task.id = affected.id "
            "RETURNING task.id, task.opportunity_id, task.state_version"
            ") INSERT INTO follow_up_task_events ("
            "id, task_id, opportunity_id, event_type, from_status, to_status, "
            "state_version, actor_type, routing_agent_id, automation_agent_id, "
            "target_channel, control_version, automation_version, "
            "scheduled_policy_version, executed_policy_version, consent_record_id, "
            "executed_consent_record_id, chat_message_id, outbound_message_id, "
            "safe_code, correlation_id, idempotency_key, command_hash"
            ") SELECT md5(quarantined.id::text || '-consent-target-unknown')::uuid, "
            "quarantined.id, quarantined.opportunity_id, 'transitioned', "
            "affected.from_status, 'review_required', quarantined.state_version, "
            "'migration', affected.routing_agent_id, affected.assigned_agent_id, "
            "affected.target_channel, affected.scheduled_control_version, "
            "affected.scheduled_automation_version, "
            "affected.scheduled_policy_version, affected.executed_policy_version, "
            "affected.consent_record_id, affected.executed_consent_record_id, "
            "affected.chat_message_id, affected.outbound_message_id, "
            "'commercial_consent_target_unknown', 'migration-f6a0b2c4d789', "
            "'consent-target-unknown-' || quarantined.id::text, "
            "md5(quarantined.id::text || '-consent-target-unknown-1') || "
            "md5(quarantined.id::text || '-consent-target-unknown-2') "
            "FROM quarantined JOIN affected ON affected.id = quarantined.id"
        )
    )


def _block_lossy_downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS ("
            "SELECT 1 FROM consent_records WHERE target_channel IS NOT NULL "
            "OR actor_admin_id IS NOT NULL"
            ") OR EXISTS ("
            "SELECT 1 FROM follow_up_task_events "
            "WHERE caused_by_consent_record_id IS NOT NULL "
            "OR idempotency_key LIKE 'consent-target-unknown-%'"
            ") THEN RAISE EXCEPTION "
            "'target-scoped consent evidence must be preserved before downgrade'; "
            "END IF; END $$"
        )
    )
