"""Add deterministic agent handoff routes and command receipts.

Revision ID: d0e4f6a8b123
Revises: c9d3e5f7a012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0e4f6a8b123"
down_revision: str | None = "c9d3e5f7a012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_handoff_routes",
        sa.Column(
            "source_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "target_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "updated_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
            "control_version >= 0",
            name="ck_agent_handoff_route_control_version",
        ),
        sa.CheckConstraint(
            "source_agent_id <> target_agent_id",
            name="ck_agent_handoff_route_distinct_agents",
        ),
        sa.CheckConstraint(
            "trigger IN ('quote_requested', 'manual_escalation')",
            name="ck_agent_handoff_route_trigger",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_agent_id"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_agent_id",
            "trigger",
            name="uq_agent_handoff_route_source_trigger",
        ),
    )
    _create_route_indexes()

    op.create_table(
        "agent_handoff_route_receipts",
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "actor_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("command_type", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column(
            "previous_target_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "target_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("previous_is_active", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "command_type IN ('created', 'updated', 'deactivated')",
            name="ck_agent_handoff_receipt_command_type",
        ),
        sa.CheckConstraint(
            "control_version >= 0",
            name="ck_agent_handoff_receipt_control_version",
        ),
        sa.CheckConstraint(
            "char_length(command_hash) = 64",
            name="ck_agent_handoff_receipt_command_hash",
        ),
        sa.CheckConstraint(
            "source_agent_id <> target_agent_id",
            name="ck_agent_handoff_receipt_distinct_agents",
        ),
        sa.CheckConstraint(
            "previous_target_agent_id IS NULL OR "
            "source_agent_id <> previous_target_agent_id",
            name="ck_agent_handoff_receipt_distinct_previous_agent",
        ),
        sa.CheckConstraint(
            "trigger IN ('quote_requested', 'manual_escalation')",
            name="ck_agent_handoff_receipt_trigger",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_target_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["agent_handoff_routes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_agent_id"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_agent_id",
            "idempotency_key",
            name="uq_agent_handoff_receipt_source_idempotency",
        ),
    )
    _create_receipt_indexes()


def downgrade() -> None:
    _drop_receipt_indexes()
    op.drop_table("agent_handoff_route_receipts")
    _drop_route_indexes()
    op.drop_table("agent_handoff_routes")


def _create_route_indexes() -> None:
    op.create_index(
        "ix_agent_handoff_route_source_active",
        "agent_handoff_routes",
        ["source_agent_id", "is_active"],
        unique=False,
    )
    for column in (
        "created_by_admin_id",
        "source_agent_id",
        "target_agent_id",
        "trigger",
        "updated_by_admin_id",
    ):
        op.create_index(
            f"ix_agent_handoff_routes_{column}",
            "agent_handoff_routes",
            [column],
            unique=False,
        )


def _drop_route_indexes() -> None:
    for column in reversed(
        (
            "created_by_admin_id",
            "source_agent_id",
            "target_agent_id",
            "trigger",
            "updated_by_admin_id",
        )
    ):
        op.drop_index(
            f"ix_agent_handoff_routes_{column}",
            table_name="agent_handoff_routes",
        )
    op.drop_index(
        "ix_agent_handoff_route_source_active",
        table_name="agent_handoff_routes",
    )


def _create_receipt_indexes() -> None:
    op.create_index(
        "ix_agent_handoff_receipt_route_created",
        "agent_handoff_route_receipts",
        ["route_id", "created_at"],
        unique=False,
    )
    for column in ("actor_admin_id", "route_id", "source_agent_id"):
        op.create_index(
            f"ix_agent_handoff_route_receipts_{column}",
            "agent_handoff_route_receipts",
            [column],
            unique=False,
        )


def _drop_receipt_indexes() -> None:
    for column in reversed(("actor_admin_id", "route_id", "source_agent_id")):
        op.drop_index(
            f"ix_agent_handoff_route_receipts_{column}",
            table_name="agent_handoff_route_receipts",
        )
    op.drop_index(
        "ix_agent_handoff_receipt_route_created",
        table_name="agent_handoff_route_receipts",
    )
