"""scope audit logs by agent and channel route

Revision ID: e3a4b5c6d7e8
Revises: d824b7f13a0e
Create Date: 2026-08-29 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a4b5c6d7e8"
down_revision: str | None = "d824b7f13a0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows intentionally remain NULL: their owning agent and route
    # cannot be established truthfully from legacy audit data.
    op.add_column("audit_logs", sa.Column("agent_id", sa.UUID(), nullable=True))
    op.add_column("audit_logs", sa.Column("channel_route_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_audit_logs_agent_id_agent_profiles",
        "audit_logs",
        "agent_profiles",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_audit_logs_channel_route_id_channel_agent_routes",
        "audit_logs",
        "channel_agent_routes",
        ["channel_route_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audit_logs_agent_id", "audit_logs", ["agent_id"])
    op.create_index(
        "ix_audit_logs_channel_route_id", "audit_logs", ["channel_route_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_channel_route_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_agent_id", table_name="audit_logs")
    op.drop_constraint(
        "fk_audit_logs_channel_route_id_channel_agent_routes",
        "audit_logs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_audit_logs_agent_id_agent_profiles",
        "audit_logs",
        type_="foreignkey",
    )
    op.drop_column("audit_logs", "channel_route_id")
    op.drop_column("audit_logs", "agent_id")
