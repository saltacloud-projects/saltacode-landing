"""remove unused request quotas and usage estimates

Revision ID: d824b7f13a0e
Revises: b7e4a1c2d930
Create Date: 2026-08-28 23:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d824b7f13a0e"
down_revision: str | None = "b7e4a1c2d930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_unused_legacy_state() -> None:
    bind = op.get_bind()
    usage_rows = bind.execute(
        sa.text("SELECT count(*) FROM usage_records")
    ).scalar_one()
    if usage_rows:
        raise RuntimeError(
            "Cannot remove usage_records while it contains data; archive or explicitly discard those legacy estimates first"
        )
    custom_quotas = bind.execute(
        sa.text("SELECT count(*) FROM authorized_users WHERE monthly_quota <> 50")
    ).scalar_one()
    if custom_quotas:
        raise RuntimeError(
            "Cannot remove monthly_quota while non-default legacy values exist; review them before migrating"
        )


def upgrade() -> None:
    _require_unused_legacy_state()
    op.drop_table("usage_records")
    op.drop_column("authorized_users", "monthly_quota")


def downgrade() -> None:
    op.add_column(
        "authorized_users",
        sa.Column(
            "monthly_quota",
            sa.Integer(),
            server_default=sa.text("50"),
            nullable=False,
        ),
    )
    op.create_table(
        "usage_records",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("requests_count", sa.Integer(), nullable=False),
        sa.Column("tokens_estimate", sa.Integer(), nullable=False),
        sa.Column("cost_estimate", sa.Numeric(10, 4), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
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
            ["user_id"], ["authorized_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "phone_number", "period_year", "period_month", name="uq_usage_period"
        ),
    )
    op.create_index("ix_usage_records_phone_number", "usage_records", ["phone_number"])
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])
