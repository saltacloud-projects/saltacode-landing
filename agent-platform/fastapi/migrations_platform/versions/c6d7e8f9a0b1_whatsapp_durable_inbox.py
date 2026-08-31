"""Add the durable route-scoped WhatsApp inbox.

Revision ID: c6d7e8f9a0b1
Revises: f4b5c6d7e8f9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "f4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_inbound_jobs",
        sa.Column("channel_route_id", sa.UUID(), nullable=False),
        sa.Column("channel_connection_id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column(
            "payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_whatsapp_inbound_job_attempts",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_whatsapp_inbound_job_status",
        ),
        sa.ForeignKeyConstraint(
            ["channel_connection_id"],
            ["channel_connections.id"],
            name=op.f(
                "fk_whatsapp_inbound_jobs_channel_connection_id_channel_connections"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["channel_route_id"],
            ["channel_agent_routes.id"],
            name=op.f("fk_whatsapp_inbound_jobs_channel_route_id_channel_agent_routes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_inbound_jobs")),
        sa.UniqueConstraint(
            "channel_route_id",
            "provider_message_id",
            name="uq_whatsapp_inbound_job_route_message",
        ),
    )
    op.create_index(
        "ix_whatsapp_inbound_job_claim",
        "whatsapp_inbound_jobs",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_inbound_jobs_channel_connection_id"),
        "whatsapp_inbound_jobs",
        ["channel_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_inbound_jobs_channel_route_id"),
        "whatsapp_inbound_jobs",
        ["channel_route_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_inbound_jobs_locked_at"),
        "whatsapp_inbound_jobs",
        ["locked_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_inbound_jobs_next_attempt_at"),
        "whatsapp_inbound_jobs",
        ["next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_inbound_jobs_status"),
        "whatsapp_inbound_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_whatsapp_inbound_jobs_status"),
        table_name="whatsapp_inbound_jobs",
    )
    op.drop_index(
        op.f("ix_whatsapp_inbound_jobs_next_attempt_at"),
        table_name="whatsapp_inbound_jobs",
    )
    op.drop_index(
        op.f("ix_whatsapp_inbound_jobs_locked_at"),
        table_name="whatsapp_inbound_jobs",
    )
    op.drop_index(
        op.f("ix_whatsapp_inbound_jobs_channel_connection_id"),
        table_name="whatsapp_inbound_jobs",
    )
    op.drop_index(
        op.f("ix_whatsapp_inbound_jobs_channel_route_id"),
        table_name="whatsapp_inbound_jobs",
    )
    op.drop_index("ix_whatsapp_inbound_job_claim", table_name="whatsapp_inbound_jobs")
    op.drop_table("whatsapp_inbound_jobs")
