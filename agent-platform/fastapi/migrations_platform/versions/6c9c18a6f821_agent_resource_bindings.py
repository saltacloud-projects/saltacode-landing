"""add explicit agent resource bindings

Revision ID: 6c9c18a6f821
Revises: 9ffe2a3e79cd
Create Date: 2026-08-27 20:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "6c9c18a6f821"
down_revision: str | None = "9ffe2a3e79cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _binding_table(
    table_name: str,
    resource_column: str,
    resource_table: str,
    unique_name: str,
) -> None:
    op.create_table(
        table_name,
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(resource_column, sa.UUID(), nullable=False),
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
            ["agent_id"], ["agent_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            [resource_column], [f"{resource_table}.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", resource_column, name=unique_name),
    )
    op.create_index(f"ix_{table_name}_agent_id", table_name, ["agent_id"])
    op.create_index(f"ix_{table_name}_{resource_column}", table_name, [resource_column])


def _backfill_binding(
    table_name: str,
    resource_column: str,
    resource_table: str,
    default_slug: str,
) -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO {table_name} (id, agent_id, {resource_column})
            SELECT gen_random_uuid(), agent_profiles.id, resources.id
            FROM agent_profiles
            CROSS JOIN {resource_table} AS resources
            WHERE agent_profiles.slug = :default_slug
            ON CONFLICT (agent_id, {resource_column}) DO NOTHING
            """
        ).bindparams(
            sa.bindparam(
                "default_slug",
                value=default_slug,
                literal_execute=True,
            )
        )
    )


def upgrade() -> None:
    bindings = (
        (
            "agent_source_bindings",
            "source_id",
            "integration_sources",
            "uq_agent_source_binding",
        ),
        (
            "agent_tool_bindings",
            "tool_id",
            "tool_registry",
            "uq_agent_tool_binding",
        ),
        (
            "agent_knowledge_block_bindings",
            "knowledge_block_id",
            "knowledge_blocks",
            "uq_agent_knowledge_block_binding",
        ),
        (
            "agent_organization_area_bindings",
            "area_id",
            "organization_areas",
            "uq_agent_organization_area_binding",
        ),
    )
    for table_name, resource_column, resource_table, unique_name in bindings:
        _binding_table(table_name, resource_column, resource_table, unique_name)

    default_slug = settings.default_agent_slug.strip()
    if default_slug:
        for table_name, resource_column, resource_table, _ in bindings:
            _backfill_binding(
                table_name,
                resource_column,
                resource_table,
                default_slug,
            )


def downgrade() -> None:
    op.drop_table("agent_organization_area_bindings")
    op.drop_table("agent_knowledge_block_bindings")
    op.drop_table("agent_tool_bindings")
    op.drop_table("agent_source_bindings")
