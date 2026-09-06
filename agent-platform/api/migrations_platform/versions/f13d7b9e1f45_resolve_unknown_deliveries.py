"""Add fail-closed resolution evidence for uncertain outbound deliveries.

Revision ID: f13d7b9e1f45
Revises: f12c6a8d0e34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f13d7b9e1f45"
down_revision: str | None = "f12c6a8d0e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column(
            "resolution_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_outbound_message_resolution_version",
        "outbound_messages",
        "resolution_version >= 0",
    )
    op.create_table(
        "outbound_delivery_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "outbound_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("resolution_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("provider_message_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_message_suffix", sa.String(length=6), nullable=True),
        sa.Column("evidence_source", sa.String(length=30), nullable=True),
        sa.Column("reason_code", sa.String(length=60), nullable=True),
        sa.Column(
            "actor_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('confirm_delivered', 'confirm_not_delivered')",
            name="ck_outbound_delivery_resolution_action",
        ),
        sa.CheckConstraint(
            "resolution_version > 0",
            name="ck_outbound_delivery_resolution_version",
        ),
        sa.CheckConstraint(
            "(action = 'confirm_delivered' "
            "AND provider_message_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_message_suffix) BETWEEN 1 AND 6 "
            "AND evidence_source IN ('provider_api', 'provider_console') "
            "AND reason_code IS NULL) OR "
            "(action = 'confirm_not_delivered' "
            "AND provider_message_hash IS NULL "
            "AND provider_message_suffix IS NULL "
            "AND evidence_source IS NULL "
            "AND reason_code IN ('provider_confirmed_not_delivered', "
            "'provider_record_not_found', 'operator_verified_not_delivered'))",
            name="ck_outbound_delivery_resolution_evidence",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0 "
            "AND char_length(btrim(correlation_id)) > 0 "
            "AND command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_outbound_delivery_resolution_command",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outbound_message_id"],
            ["outbound_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "outbound_message_id",
            "idempotency_key",
            name="uq_outbound_delivery_resolution_idempotency",
        ),
        sa.UniqueConstraint(
            "outbound_message_id",
            "resolution_version",
            name="uq_outbound_delivery_resolution_version",
        ),
    )
    op.create_index(
        "ix_outbound_delivery_resolution_message_created",
        "outbound_delivery_resolutions",
        ["outbound_message_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_evidence = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM outbound_delivery_resolutions)")
    ).scalar_one()
    if has_evidence:
        raise RuntimeError(
            "outbound delivery resolution evidence must be preserved; "
            "downgrade is blocked"
        )
    op.drop_index(
        "ix_outbound_delivery_resolution_message_created",
        table_name="outbound_delivery_resolutions",
    )
    op.drop_table("outbound_delivery_resolutions")
    op.drop_constraint(
        "ck_outbound_message_resolution_version",
        "outbound_messages",
        type_="check",
    )
    op.drop_column("outbound_messages", "resolution_version")
