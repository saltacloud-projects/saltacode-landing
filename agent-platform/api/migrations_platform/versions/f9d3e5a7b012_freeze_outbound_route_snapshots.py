"""Freeze outbound route and adapter snapshots.

Revision ID: f9d3e5a7b012
Revises: f8c2d4e6a901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f9d3e5a7b012"
down_revision: str | None = "f8c2d4e6a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "outbound_messages"
_SNAPSHOT_COLUMNS = (
    "channel",
    "adapter_key",
    "channel_connection_id",
    "route_version",
    "connection_version",
)


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("channel", sa.String(length=30), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("adapter_key", sa.String(length=80), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "channel_connection_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(_TABLE, sa.Column("route_version", sa.Integer(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("connection_version", sa.Integer(), nullable=True),
    )

    _quarantine_legacy_active_commands()

    op.create_check_constraint(
        "ck_outbound_message_route_snapshot_set",
        _TABLE,
        "(channel IS NULL AND adapter_key IS NULL "
        "AND channel_connection_id IS NULL AND route_version IS NULL "
        "AND connection_version IS NULL) OR "
        "(channel IS NOT NULL AND adapter_key IS NOT NULL "
        "AND channel_connection_id IS NOT NULL AND route_version IS NOT NULL "
        "AND connection_version IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_outbound_message_route_snapshot_versions",
        _TABLE,
        "(route_version IS NULL OR route_version >= 0) "
        "AND (connection_version IS NULL OR connection_version >= 0)",
    )
    op.create_check_constraint(
        "ck_outbound_message_active_route_snapshot",
        _TABLE,
        "status NOT IN ('queued', 'dispatching') OR channel IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_outbound_message_channel_connection",
        _TABLE,
        "channel_connections",
        ["channel_connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_outbound_messages_channel",
        _TABLE,
        ["channel"],
    )
    op.create_index(
        "ix_outbound_messages_channel_connection_id",
        _TABLE,
        ["channel_connection_id"],
    )
    _create_snapshot_immutability_trigger()


def downgrade() -> None:
    _block_snapshot_loss()
    op.execute(
        "DROP TRIGGER outbound_messages_freeze_route_snapshot ON outbound_messages"
    )
    op.execute("DROP FUNCTION prevent_outbound_route_snapshot_change()")
    op.drop_index(
        "ix_outbound_messages_channel_connection_id",
        table_name=_TABLE,
    )
    op.drop_index("ix_outbound_messages_channel", table_name=_TABLE)
    op.drop_constraint(
        "fk_outbound_message_channel_connection",
        _TABLE,
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_outbound_message_active_route_snapshot",
        _TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck_outbound_message_route_snapshot_versions",
        _TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck_outbound_message_route_snapshot_set",
        _TABLE,
        type_="check",
    )
    for column in reversed(_SNAPSHOT_COLUMNS):
        op.drop_column(_TABLE, column)


def _quarantine_legacy_active_commands() -> None:
    op.execute(
        sa.text(
            "WITH cancelled AS ("
            "UPDATE outbound_messages SET status = 'cancelled', "
            "locked_by = NULL, locked_at = NULL "
            "WHERE status = 'queued' AND channel IS NULL "
            "RETURNING id"
            ") "
            "INSERT INTO outbound_delivery_events "
            "(id, outbound_message_id, attempt_id, event_type, from_status, "
            "to_status, actor_type, actor_id, safe_code, created_at) "
            "SELECT gen_random_uuid(), id, NULL, 'cancelled', 'queued', "
            "'cancelled', 'system', NULL, 'legacy_route_snapshot_missing', now() "
            "FROM cancelled"
        )
    )
    op.execute(
        sa.text(
            "WITH uncertain AS ("
            "UPDATE outbound_messages SET status = 'delivery_unknown', "
            "locked_by = NULL, locked_at = NULL "
            "WHERE status = 'dispatching' AND channel IS NULL "
            "RETURNING id"
            ") "
            "INSERT INTO outbound_delivery_events "
            "(id, outbound_message_id, attempt_id, event_type, from_status, "
            "to_status, actor_type, actor_id, safe_code, created_at) "
            "SELECT gen_random_uuid(), id, NULL, 'delivery_unknown', 'dispatching', "
            "'delivery_unknown', 'system', NULL, "
            "'legacy_route_snapshot_missing', now() FROM uncertain"
        )
    )


def _create_snapshot_immutability_trigger() -> None:
    op.execute(
        "CREATE FUNCTION prevent_outbound_route_snapshot_change() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF OLD.channel_route_id IS DISTINCT FROM NEW.channel_route_id "
        "OR OLD.channel IS DISTINCT FROM NEW.channel "
        "OR OLD.adapter_key IS DISTINCT FROM NEW.adapter_key "
        "OR OLD.channel_connection_id IS DISTINCT FROM NEW.channel_connection_id "
        "OR OLD.route_version IS DISTINCT FROM NEW.route_version "
        "OR OLD.connection_version IS DISTINCT FROM NEW.connection_version "
        "THEN RAISE EXCEPTION 'outbound route snapshot is immutable'; "
        "END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER outbound_messages_freeze_route_snapshot "
        "BEFORE UPDATE ON outbound_messages FOR EACH ROW "
        "EXECUTE FUNCTION prevent_outbound_route_snapshot_change()"
    )


def _block_snapshot_loss() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM outbound_messages "
            "WHERE channel IS NOT NULL OR adapter_key IS NOT NULL "
            "OR channel_connection_id IS NOT NULL OR route_version IS NOT NULL "
            "OR connection_version IS NOT NULL) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade: outbound route snapshots must be preserved'; "
            "END IF; END $$"
        )
    )
