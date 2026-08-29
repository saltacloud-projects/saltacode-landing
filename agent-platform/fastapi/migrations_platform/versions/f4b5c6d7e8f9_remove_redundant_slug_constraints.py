"""remove redundant connection slug constraints

Revision ID: f4b5c6d7e8f9
Revises: e3a4b5c6d7e8
Create Date: 2026-08-29 01:15:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b5c6d7e8f9"
down_revision: str | None = "e3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The original migration created both an unnamed UNIQUE constraint and a
    # named unique index for each slug. Keep the named indexes used by the ORM
    # and remove only the redundant constraints and their backing indexes.
    op.drop_constraint(
        "provider_connections_slug_key",
        "provider_connections",
        type_="unique",
    )
    op.drop_constraint(
        "channel_connections_slug_key",
        "channel_connections",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "channel_connections_slug_key",
        "channel_connections",
        ["slug"],
    )
    op.create_unique_constraint(
        "provider_connections_slug_key",
        "provider_connections",
        ["slug"],
    )
