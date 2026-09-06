"""Add durable administrator grants scoped to one agent.

Revision ID: b8c2d4e6f901
Revises: a6f1d2c3e4b5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8c2d4e6f901"
down_revision: str | None = "a6f1d2c3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_agent_grants",
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "admin_user_id",
            "agent_id",
            name="uq_admin_agent_grants_admin_agent",
        ),
    )
    op.create_index(
        op.f("ix_admin_agent_grants_admin_user_id"),
        "admin_agent_grants",
        ["admin_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_agent_grants_agent_id"),
        "admin_agent_grants",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_agent_grants_is_active"),
        "admin_agent_grants",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_agent_grants_is_active"),
        table_name="admin_agent_grants",
    )
    op.drop_index(
        op.f("ix_admin_agent_grants_agent_id"),
        table_name="admin_agent_grants",
    )
    op.drop_index(
        op.f("ix_admin_agent_grants_admin_user_id"),
        table_name="admin_agent_grants",
    )
    op.drop_table("admin_agent_grants")
