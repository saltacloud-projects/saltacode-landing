"""Add explicit commercial progression without changing existing behavior.

Revision ID: f14e8c0f2a56
Revises: f13d7b9e1f45
"""

import sqlalchemy as sa
from alembic import op

revision = "f14e8c0f2a56"
down_revision = "f13d7b9e1f45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_progression_policies",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("quote_request_action", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("agent_id"),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "quote_request_action IN ('keep_agent', 'handoff')",
            name="ck_commercial_progression_action",
        ),
        sa.CheckConstraint("version >= 1", name="ck_commercial_progression_version"),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM commercial_progression_policies)")
        )
        .scalar()
    ):
        raise RuntimeError("Cannot discard persisted commercial progression policy")
    op.drop_table("commercial_progression_policies")
