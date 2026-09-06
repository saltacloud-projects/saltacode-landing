"""Generalize external-channel ingress and quarantine legacy payloads.

Revision ID: f12c6a8d0e34
Revises: f11b5f7c9d23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f12c6a8d0e34"
down_revision: str | None = "f11b5f7c9d23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = (
    "queued",
    "processing",
    "completed",
    "routed_to_human",
    "ignored",
    "review_required",
    "cancelled",
)
_PHASES = (
    "accepted",
    "legacy_quarantined",
    "claimed",
    "inbound_recorded",
    "provider_effect_started",
    "transcription_started",
    "agent_effect_started",
    "outbox_effect_started",
    "terminal",
)
_EVENTS = (
    "accepted",
    "legacy_completed_migrated",
    "legacy_quarantined",
    "claimed",
    "phase_advanced",
    "completed",
    "routed_to_human",
    "review_required",
    "requeued",
    "cancelled",
    "acknowledged",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    connection = op.get_bind()
    unsafe_completed = connection.execute(
        sa.text(
            "SELECT count(*) FROM whatsapp_inbound_jobs "
            "WHERE status = 'completed' AND payload_json <> '{}'::jsonb"
        )
    ).scalar_one()
    if unsafe_completed:
        raise RuntimeError(
            "f12 refuses to discard an unexpected completed legacy payload"
        )

    op.drop_index("ix_whatsapp_inbound_job_claim", table_name="whatsapp_inbound_jobs")
    op.drop_index(
        "ix_whatsapp_inbound_jobs_locked_at", table_name="whatsapp_inbound_jobs"
    )
    op.drop_index(
        "ix_whatsapp_inbound_jobs_next_attempt_at",
        table_name="whatsapp_inbound_jobs",
    )
    op.execute("ALTER TABLE whatsapp_inbound_jobs RENAME TO channel_inbound_jobs")
    for old_name, new_name in (
        (
            "uq_whatsapp_inbound_job_route_message",
            "uq_channel_inbound_job_route_message",
        ),
    ):
        op.execute(
            f"ALTER TABLE channel_inbound_jobs RENAME CONSTRAINT {old_name} TO {new_name}"
        )
    for old_name, new_name in (
        (
            "ix_whatsapp_inbound_jobs_channel_route_id",
            "ix_channel_inbound_jobs_channel_route_id",
        ),
        (
            "ix_whatsapp_inbound_jobs_channel_connection_id",
            "ix_channel_inbound_jobs_channel_connection_id",
        ),
        ("ix_whatsapp_inbound_jobs_status", "ix_channel_inbound_jobs_status"),
    ):
        op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")

    op.drop_constraint(
        "ck_whatsapp_inbound_job_status",
        "channel_inbound_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_whatsapp_inbound_job_attempts",
        "channel_inbound_jobs",
        type_="check",
    )
    for old_name, new_name in (
        ("payload_json", "legacy_payload_json"),
        ("max_attempts", "legacy_max_attempts"),
        ("locked_by", "legacy_locked_by"),
        ("locked_at", "legacy_locked_at"),
        ("next_attempt_at", "legacy_next_attempt_at"),
        ("error_code", "legacy_error_code"),
        ("error_message", "legacy_error_message"),
        ("completed_at", "terminal_at"),
    ):
        op.alter_column("channel_inbound_jobs", old_name, new_column_name=new_name)

    for column in (
        sa.Column("channel", sa.String(length=30), nullable=True),
        sa.Column("adapter_key", sa.String(length=80), nullable=True),
        sa.Column("adapter_version", sa.Integer(), nullable=True),
        sa.Column("channel_route_version", sa.Integer(), nullable=True),
        sa.Column("route_key_snapshot", sa.String(length=120), nullable=True),
        sa.Column("channel_connection_version", sa.Integer(), nullable=True),
        sa.Column("routing_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("thread_key", sa.String(length=64), nullable=True),
        sa.Column("payload_ciphertext", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("phase", sa.String(length=40), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_code", sa.String(length=80), nullable=True),
        sa.Column("legacy_status", sa.String(length=20), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_control_version", sa.Integer(), nullable=True),
        sa.Column("automation_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_automation_version", sa.Integer(), nullable=True),
    ):
        op.add_column("channel_inbound_jobs", column)

    op.execute(
        "UPDATE channel_inbound_jobs AS job SET "
        "channel = route.channel, adapter_key = conn.adapter_key, adapter_version = 1, "
        "channel_route_version = route.version, route_key_snapshot = route.route_key, "
        "channel_connection_version = conn.version, routing_agent_id = route.agent_id, "
        "legacy_status = job.status, "
        "phase = CASE WHEN job.status = 'completed' THEN 'terminal' "
        "ELSE 'legacy_quarantined' END, state_version = 0, "
        "safe_code = CASE WHEN job.status = 'completed' THEN NULL "
        "ELSE 'legacy_payload_quarantined' END, "
        "legacy_payload_json = CASE WHEN job.status = 'completed' THEN NULL "
        "ELSE legacy_payload_json END, "
        "status = CASE WHEN job.status = 'completed' THEN 'completed' "
        "ELSE 'review_required' END "
        "FROM channel_agent_routes AS route, channel_connections AS conn "
        "WHERE route.id = job.channel_route_id "
        "AND conn.id = job.channel_connection_id"
    )
    for column_name in (
        "channel",
        "adapter_key",
        "adapter_version",
        "channel_route_version",
        "route_key_snapshot",
        "channel_connection_version",
        "routing_agent_id",
        "phase",
        "state_version",
    ):
        op.alter_column("channel_inbound_jobs", column_name, nullable=False)
    op.alter_column(
        "channel_inbound_jobs",
        "legacy_payload_json",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )
    op.alter_column(
        "channel_inbound_jobs",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=24),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_channel_inbound_jobs_routing_agent_id_agent_profiles",
        "channel_inbound_jobs",
        "agent_profiles",
        ["routing_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_channel_inbound_jobs_conversation_id_chat_conversations",
        "channel_inbound_jobs",
        "chat_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_channel_inbound_jobs_automation_agent_id_agent_profiles",
        "channel_inbound_jobs",
        "agent_profiles",
        ["automation_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _create_job_constraints()
    for index_name, columns in (
        ("ix_channel_inbound_jobs_channel", ["channel"]),
        ("ix_channel_inbound_jobs_routing_agent_id", ["routing_agent_id"]),
        ("ix_channel_inbound_jobs_lease_expires_at", ["lease_expires_at"]),
        ("ix_channel_inbound_jobs_conversation_id", ["conversation_id"]),
        ("ix_channel_inbound_job_claim", ["status", "created_at", "id"]),
        (
            "ix_channel_inbound_job_thread_fifo",
            ["thread_key", "created_at", "id"],
        ),
        (
            "ix_channel_inbound_job_agent_status",
            ["routing_agent_id", "status", "updated_at"],
        ),
    ):
        op.create_index(index_name, "channel_inbound_jobs", columns)

    _create_events_table()
    op.execute(
        "INSERT INTO channel_inbound_events ("
        "id, job_id, event_type, from_status, to_status, state_version, phase, "
        "actor_type, safe_code, channel, adapter_key, adapter_version, "
        "channel_route_id, channel_route_version, channel_connection_id, "
        "channel_connection_version, routing_agent_id, evidence_json, created_at"
        ") SELECT gen_random_uuid(), id, "
        "CASE WHEN status = 'completed' THEN 'legacy_completed_migrated' "
        "ELSE 'legacy_quarantined' END, "
        "legacy_status, status, 0, phase, 'system', safe_code, channel, "
        "adapter_key, adapter_version, channel_route_id, channel_route_version, "
        "channel_connection_id, channel_connection_version, routing_agent_id, "
        "'{}'::jsonb, created_at FROM channel_inbound_jobs"
    )
    _create_immutability_guards()


def _create_job_constraints() -> None:
    table = "channel_inbound_jobs"
    op.create_check_constraint(
        "ck_channel_inbound_job_channel",
        table,
        "channel IN ('whatsapp', 'email', 'instagram_dm', 'facebook_messenger')",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_status", table, f"status IN ({_sql_values(_STATUSES)})"
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_phase", table, f"phase IN ({_sql_values(_PHASES)})"
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_versions",
        table,
        "state_version >= 0 AND attempts >= 0",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_snapshots",
        table,
        "channel_route_version >= 0 AND channel_connection_version >= 0 "
        "AND adapter_version > 0",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_thread_key",
        table,
        "thread_key IS NULL OR thread_key ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_payload_hash",
        table,
        "payload_hash IS NULL OR payload_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_payload_pair",
        table,
        "(payload_ciphertext IS NULL) = (payload_hash IS NULL)",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_executable_payload",
        table,
        "status NOT IN ('queued', 'processing') OR "
        "(thread_key IS NOT NULL AND payload_ciphertext IS NOT NULL "
        "AND legacy_payload_json IS NULL)",
    )
    op.create_check_constraint(
        "ck_channel_inbound_job_lease",
        table,
        "(status = 'processing' AND lease_owner IS NOT NULL "
        "AND lease_expires_at IS NOT NULL) OR "
        "(status <> 'processing' AND lease_owner IS NULL "
        "AND lease_expires_at IS NULL)",
    )


def _create_events_table() -> None:
    op.create_table(
        "channel_inbound_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("safe_code", sa.String(length=80), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=220), nullable=True),
        sa.Column("command_hash", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("adapter_key", sa.String(length=80), nullable=False),
        sa.Column("adapter_version", sa.Integer(), nullable=False),
        sa.Column("channel_route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_route_version", sa.Integer(), nullable=False),
        sa.Column(
            "channel_connection_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("channel_connection_version", sa.Integer(), nullable=False),
        sa.Column("routing_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_control_version", sa.Integer(), nullable=True),
        sa.Column("automation_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_automation_version", sa.Integer(), nullable=True),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"event_type IN ({_sql_values(_EVENTS)})",
            name="ck_channel_inbound_event_type",
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN "
            f"({_sql_values(_STATUSES + ('failed',))})",
            name="ck_channel_inbound_event_from_status",
        ),
        sa.CheckConstraint(
            f"to_status IN ({_sql_values(_STATUSES)})",
            name="ck_channel_inbound_event_to_status",
        ),
        sa.CheckConstraint(
            f"phase IN ({_sql_values(_PHASES)})",
            name="ck_channel_inbound_event_phase",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_channel_inbound_event_version"
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'worker', 'operator')",
            name="ck_channel_inbound_event_actor_type",
        ),
        sa.CheckConstraint(
            "(actor_type = 'operator' AND actor_admin_id IS NOT NULL) OR "
            "(actor_type <> 'operator' AND actor_admin_id IS NULL)",
            name="ck_channel_inbound_event_actor",
        ),
        sa.CheckConstraint(
            "command_hash IS NULL OR command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_channel_inbound_event_command_hash",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["channel_inbound_jobs.id"],
            name="fk_channel_inbound_events_job_id_channel_inbound_jobs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            name="fk_channel_inbound_events_actor_admin_id_admin_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_channel_inbound_events"),
        sa.UniqueConstraint(
            "job_id",
            "state_version",
            name="uq_channel_inbound_event_state_version",
        ),
        sa.UniqueConstraint(
            "job_id",
            "idempotency_key",
            name="uq_channel_inbound_event_idempotency",
        ),
    )
    op.create_index(
        "ix_channel_inbound_events_job_id", "channel_inbound_events", ["job_id"]
    )
    op.create_index(
        "ix_channel_inbound_event_job_created",
        "channel_inbound_events",
        ["job_id", "created_at"],
    )


def _create_immutability_guards() -> None:
    op.execute(
        "CREATE FUNCTION channel_inbound_freeze_acceptance_snapshot() "
        "RETURNS trigger AS $$ BEGIN "
        "IF ROW(OLD.channel, OLD.adapter_key, OLD.adapter_version, "
        "OLD.channel_route_id, OLD.channel_route_version, OLD.route_key_snapshot, "
        "OLD.channel_connection_id, OLD.channel_connection_version, "
        "OLD.routing_agent_id, OLD.provider_message_id) IS DISTINCT FROM "
        "ROW(NEW.channel, NEW.adapter_key, NEW.adapter_version, "
        "NEW.channel_route_id, NEW.channel_route_version, NEW.route_key_snapshot, "
        "NEW.channel_connection_id, NEW.channel_connection_version, "
        "NEW.routing_agent_id, NEW.provider_message_id) "
        "OR (OLD.thread_key IS NOT NULL "
        "AND OLD.thread_key IS DISTINCT FROM NEW.thread_key) "
        "THEN RAISE EXCEPTION 'channel inbound acceptance snapshot is immutable'; "
        "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER channel_inbound_jobs_freeze_acceptance_snapshot "
        "BEFORE UPDATE ON channel_inbound_jobs FOR EACH ROW "
        "EXECUTE FUNCTION channel_inbound_freeze_acceptance_snapshot()"
    )


def downgrade() -> None:
    row_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM channel_inbound_jobs"))
        .scalar_one()
    )
    if row_count:
        raise RuntimeError(
            "f12 downgrade is blocked while channel ingress evidence exists"
        )

    op.execute(
        "DROP TRIGGER channel_inbound_jobs_freeze_acceptance_snapshot "
        "ON channel_inbound_jobs"
    )
    op.execute("DROP FUNCTION channel_inbound_freeze_acceptance_snapshot()")
    op.drop_table("channel_inbound_events")
    for index_name in (
        "ix_channel_inbound_job_agent_status",
        "ix_channel_inbound_job_thread_fifo",
        "ix_channel_inbound_job_claim",
        "ix_channel_inbound_jobs_conversation_id",
        "ix_channel_inbound_jobs_lease_expires_at",
        "ix_channel_inbound_jobs_routing_agent_id",
        "ix_channel_inbound_jobs_channel",
    ):
        op.drop_index(index_name, table_name="channel_inbound_jobs")
    for constraint_name in (
        "ck_channel_inbound_job_lease",
        "ck_channel_inbound_job_executable_payload",
        "ck_channel_inbound_job_payload_pair",
        "ck_channel_inbound_job_payload_hash",
        "ck_channel_inbound_job_thread_key",
        "ck_channel_inbound_job_snapshots",
        "ck_channel_inbound_job_versions",
        "ck_channel_inbound_job_phase",
        "ck_channel_inbound_job_status",
        "ck_channel_inbound_job_channel",
        "fk_channel_inbound_jobs_automation_agent_id_agent_profiles",
        "fk_channel_inbound_jobs_conversation_id_chat_conversations",
        "fk_channel_inbound_jobs_routing_agent_id_agent_profiles",
    ):
        op.drop_constraint(constraint_name, "channel_inbound_jobs")
    for column_name in (
        "conversation_automation_version",
        "automation_agent_id",
        "conversation_control_version",
        "conversation_id",
        "safe_code",
        "legacy_status",
        "lease_expires_at",
        "lease_owner",
        "state_version",
        "phase",
        "payload_hash",
        "payload_ciphertext",
        "thread_key",
        "routing_agent_id",
        "channel_connection_version",
        "route_key_snapshot",
        "channel_route_version",
        "adapter_version",
        "adapter_key",
        "channel",
    ):
        op.drop_column("channel_inbound_jobs", column_name)
    op.alter_column(
        "channel_inbound_jobs",
        "status",
        existing_type=sa.String(length=24),
        type_=sa.String(length=20),
    )
    for old_name, new_name in (
        ("legacy_payload_json", "payload_json"),
        ("legacy_max_attempts", "max_attempts"),
        ("legacy_locked_by", "locked_by"),
        ("legacy_locked_at", "locked_at"),
        ("legacy_next_attempt_at", "next_attempt_at"),
        ("legacy_error_code", "error_code"),
        ("legacy_error_message", "error_message"),
        ("terminal_at", "completed_at"),
    ):
        op.alter_column("channel_inbound_jobs", old_name, new_column_name=new_name)
    op.execute("ALTER TABLE channel_inbound_jobs RENAME TO whatsapp_inbound_jobs")
    for old_name, new_name in (
        (
            "uq_channel_inbound_job_route_message",
            "uq_whatsapp_inbound_job_route_message",
        ),
    ):
        op.execute(
            f"ALTER TABLE whatsapp_inbound_jobs RENAME CONSTRAINT {old_name} TO {new_name}"
        )
    for old_name, new_name in (
        (
            "ix_channel_inbound_jobs_channel_route_id",
            "ix_whatsapp_inbound_jobs_channel_route_id",
        ),
        (
            "ix_channel_inbound_jobs_channel_connection_id",
            "ix_whatsapp_inbound_jobs_channel_connection_id",
        ),
        ("ix_channel_inbound_jobs_status", "ix_whatsapp_inbound_jobs_status"),
    ):
        op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")
    op.create_check_constraint(
        "ck_whatsapp_inbound_job_status",
        "whatsapp_inbound_jobs",
        "status IN ('queued', 'processing', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_whatsapp_inbound_job_attempts",
        "whatsapp_inbound_jobs",
        "attempts >= 0 AND max_attempts >= 1",
    )
    op.create_index(
        "ix_whatsapp_inbound_job_claim",
        "whatsapp_inbound_jobs",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_whatsapp_inbound_jobs_locked_at",
        "whatsapp_inbound_jobs",
        ["locked_at"],
    )
    op.create_index(
        "ix_whatsapp_inbound_jobs_next_attempt_at",
        "whatsapp_inbound_jobs",
        ["next_attempt_at"],
    )
