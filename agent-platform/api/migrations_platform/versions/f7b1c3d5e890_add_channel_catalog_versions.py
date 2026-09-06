"""Add code-owned channel adapters and CAS versions.

Revision ID: f7b1c3d5e890
Revises: f6a0b2c4d789
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7b1c3d5e890"
down_revision: str | None = "f6a0b2c4d789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_connections",
        sa.Column("adapter_key", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "channel_connections",
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE channel_connections SET adapter_key = CASE channel "
            "WHEN 'web' THEN 'web_builtin' "
            "WHEN 'whatsapp' THEN 'meta_whatsapp_cloud' END"
        )
    )
    op.alter_column(
        "channel_connections",
        "adapter_key",
        existing_type=sa.String(length=80),
        nullable=False,
    )
    op.drop_constraint(
        "uq_channel_connection_account",
        "channel_connections",
        type_="unique",
    )
    op.drop_constraint(
        "ck_channel_connection_channel",
        "channel_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_channel_connection_channel",
        "channel_connections",
        "channel IN ('web', 'whatsapp', 'email', 'instagram_dm', 'facebook_messenger')",
    )
    op.create_check_constraint(
        "ck_channel_connection_adapter_key",
        "channel_connections",
        "adapter_key IN ('web_builtin', 'meta_whatsapp_cloud', 'email', "
        "'meta_instagram_graph', 'meta_messenger_graph')",
    )
    op.create_check_constraint(
        "ck_channel_connection_adapter_channel",
        "channel_connections",
        "(channel = 'web' AND adapter_key = 'web_builtin') OR "
        "(channel = 'whatsapp' AND adapter_key = 'meta_whatsapp_cloud') OR "
        "(channel = 'email' AND adapter_key = 'email') OR "
        "(channel = 'instagram_dm' AND adapter_key = 'meta_instagram_graph') OR "
        "(channel = 'facebook_messenger' AND "
        "adapter_key = 'meta_messenger_graph')",
    )
    op.create_check_constraint(
        "ck_channel_connection_version",
        "channel_connections",
        "version >= 0",
    )
    op.create_unique_constraint(
        "uq_channel_connection_adapter_account",
        "channel_connections",
        ["adapter_key", "external_account_id"],
    )
    op.create_index(
        "ix_channel_connections_adapter_key",
        "channel_connections",
        ["adapter_key"],
    )
    _create_legacy_writer_adapter_trigger()

    op.add_column(
        "channel_agent_routes",
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.drop_constraint(
        "ck_channel_agent_route_channel",
        "channel_agent_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_channel_agent_route_channel",
        "channel_agent_routes",
        "channel IN ('web', 'whatsapp', 'email', 'instagram_dm', 'facebook_messenger')",
    )
    op.create_check_constraint(
        "ck_channel_agent_route_version",
        "channel_agent_routes",
        "version >= 0",
    )


def downgrade() -> None:
    _block_lossy_downgrade()

    op.drop_constraint(
        "ck_channel_agent_route_version",
        "channel_agent_routes",
        type_="check",
    )
    op.drop_constraint(
        "ck_channel_agent_route_channel",
        "channel_agent_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_channel_agent_route_channel",
        "channel_agent_routes",
        "channel IN ('web', 'whatsapp')",
    )
    op.drop_column("channel_agent_routes", "version")

    op.drop_index(
        "ix_channel_connections_adapter_key",
        table_name="channel_connections",
    )
    op.execute(
        "DROP TRIGGER channel_connections_set_adapter_key ON channel_connections"
    )
    op.execute("DROP FUNCTION set_channel_connection_adapter_key()")
    op.drop_constraint(
        "uq_channel_connection_adapter_account",
        "channel_connections",
        type_="unique",
    )
    op.drop_constraint(
        "ck_channel_connection_version",
        "channel_connections",
        type_="check",
    )
    op.drop_constraint(
        "ck_channel_connection_adapter_channel",
        "channel_connections",
        type_="check",
    )
    op.drop_constraint(
        "ck_channel_connection_adapter_key",
        "channel_connections",
        type_="check",
    )
    op.drop_constraint(
        "ck_channel_connection_channel",
        "channel_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_channel_connection_channel",
        "channel_connections",
        "channel IN ('web', 'whatsapp')",
    )
    op.create_unique_constraint(
        "uq_channel_connection_account",
        "channel_connections",
        ["channel", "external_account_id"],
    )
    op.drop_column("channel_connections", "version")
    op.drop_column("channel_connections", "adapter_key")


def _block_lossy_downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM channel_connections "
            "WHERE channel NOT IN ('web', 'whatsapp') "
            "OR adapter_key <> CASE channel "
            "WHEN 'web' THEN 'web_builtin' "
            "WHEN 'whatsapp' THEN 'meta_whatsapp_cloud' END "
            "OR version <> 0) "
            "OR EXISTS (SELECT 1 FROM channel_agent_routes "
            "WHERE channel NOT IN ('web', 'whatsapp') OR version <> 0) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade: channel catalog or CAS evidence would be lost'; "
            "END IF; END $$"
        )
    )


def _create_legacy_writer_adapter_trigger() -> None:
    """Keep the expand-phase schema writable by the previous application revision."""

    op.execute(
        "CREATE FUNCTION set_channel_connection_adapter_key() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF NEW.adapter_key IS NULL THEN "
        "NEW.adapter_key = CASE NEW.channel "
        "WHEN 'web' THEN 'web_builtin' "
        "WHEN 'whatsapp' THEN 'meta_whatsapp_cloud' "
        "WHEN 'email' THEN 'email' "
        "WHEN 'instagram_dm' THEN 'meta_instagram_graph' "
        "WHEN 'facebook_messenger' THEN 'meta_messenger_graph' END; "
        "END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER channel_connections_set_adapter_key "
        "BEFORE INSERT OR UPDATE OF channel, adapter_key ON channel_connections "
        "FOR EACH ROW EXECUTE FUNCTION set_channel_connection_adapter_key()"
    )
