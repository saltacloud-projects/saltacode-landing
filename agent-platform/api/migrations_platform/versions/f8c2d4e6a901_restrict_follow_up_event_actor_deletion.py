"""Protect follow-up operator audit attribution.

Revision ID: f8c2d4e6a901
Revises: f7b1c3d5e890
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8c2d4e6a901"
down_revision: str | None = "f7b1c3d5e890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "follow_up_task_events"
_LEGACY_CONSTRAINT = "follow_up_task_events_actor_admin_id_fkey"
_DURABLE_CONSTRAINT = "fk_follow_up_task_event_actor_admin"


def upgrade() -> None:
    op.drop_constraint(
        _LEGACY_CONSTRAINT,
        _TABLE,
        type_="foreignkey",
    )
    op.create_foreign_key(
        _DURABLE_CONSTRAINT,
        _TABLE,
        "admin_users",
        ["actor_admin_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    _block_downgrade_with_operator_evidence()
    op.drop_constraint(
        _DURABLE_CONSTRAINT,
        _TABLE,
        type_="foreignkey",
    )
    op.create_foreign_key(
        _LEGACY_CONSTRAINT,
        _TABLE,
        "admin_users",
        ["actor_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def _block_downgrade_with_operator_evidence() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM follow_up_task_events "
            "WHERE actor_type = 'operator') "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade: operator follow-up audit evidence requires durable actor attribution'; "
            "END IF; END $$"
        )
    )
