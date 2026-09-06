"""Add durable agent-scoped identity-link claims.

Revision ID: c9d3e5f7a012
Revises: b8c2d4e6f901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d3e5f7a012"
down_revision: str | None = "b8c2d4e6f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_link_claims",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_identity_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "target_identity_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source_principal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "target_principal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("proof_method", sa.String(length=40), nullable=False),
        sa.Column("proof_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "proof_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "proof_consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("evidence_reference", sa.String(length=200), nullable=True),
        sa.Column(
            "created_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "verified_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("issue_idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("issue_command_hash", sa.String(length=64), nullable=False),
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
            name="ck_identity_link_claim_control_version",
        ),
        sa.CheckConstraint(
            "source_identity_id <> target_identity_id",
            name="ck_identity_link_claim_distinct_identities",
        ),
        sa.CheckConstraint(
            "evidence_sha256 IS NULL OR char_length(evidence_sha256) = 64",
            name="ck_identity_link_claim_evidence_hash",
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR proof_token_hash IS NOT NULL",
            name="ck_identity_link_claim_pending_proof",
        ),
        sa.CheckConstraint(
            "status = 'pending' OR proof_token_hash IS NULL",
            name="ck_identity_link_claim_terminal_proof",
        ),
        sa.CheckConstraint(
            "char_length(issue_command_hash) = 64",
            name="ck_identity_link_claim_issue_command_hash",
        ),
        sa.CheckConstraint(
            "proof_token_hash IS NULL OR char_length(proof_token_hash) = 64",
            name="ck_identity_link_claim_proof_hash",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_status",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_identity_id"],
            ["channel_identities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_principal_id"],
            ["principals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_identity_id"],
            ["channel_identities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_principal_id"],
            ["principals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "issue_idempotency_key",
            name="uq_identity_link_claim_agent_idempotency",
        ),
    )
    _create_claim_indexes()

    op.create_table(
        "identity_link_claim_events",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
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
            "control_version >= 0",
            name="ck_identity_link_claim_event_control_version",
        ),
        sa.CheckConstraint(
            "char_length(command_hash) = 64",
            name="ck_identity_link_claim_event_command_hash",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('pending', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_event_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('pending', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_event_to_status",
        ),
        sa.CheckConstraint(
            "event_type IN ('issued', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["identity_link_claims.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_identity_link_claim_event_agent_idempotency",
        ),
        sa.UniqueConstraint(
            "claim_id",
            "control_version",
            name="uq_identity_link_claim_event_version",
        ),
    )
    _create_event_indexes()


def downgrade() -> None:
    _drop_event_indexes()
    op.drop_table("identity_link_claim_events")
    _drop_claim_indexes()
    op.drop_table("identity_link_claims")


def _create_claim_indexes() -> None:
    op.create_index(
        "ix_identity_link_claim_agent_status_updated",
        "identity_link_claims",
        ["agent_id", "status", "updated_at"],
        unique=False,
    )
    for column in (
        "agent_id",
        "created_by_admin_id",
        "proof_expires_at",
        "source_identity_id",
        "source_principal_id",
        "status",
        "target_identity_id",
        "target_principal_id",
        "verified_by_admin_id",
    ):
        op.create_index(
            op.f(f"ix_identity_link_claims_{column}"),
            "identity_link_claims",
            [column],
            unique=False,
        )


def _drop_claim_indexes() -> None:
    for column in reversed(
        (
            "agent_id",
            "created_by_admin_id",
            "proof_expires_at",
            "source_identity_id",
            "source_principal_id",
            "status",
            "target_identity_id",
            "target_principal_id",
            "verified_by_admin_id",
        )
    ):
        op.drop_index(
            op.f(f"ix_identity_link_claims_{column}"),
            table_name="identity_link_claims",
        )
    op.drop_index(
        "ix_identity_link_claim_agent_status_updated",
        table_name="identity_link_claims",
    )


def _create_event_indexes() -> None:
    op.create_index(
        "ix_identity_link_claim_event_claim_created",
        "identity_link_claim_events",
        ["claim_id", "created_at"],
        unique=False,
    )
    for column in ("actor_admin_id", "agent_id", "claim_id"):
        op.create_index(
            op.f(f"ix_identity_link_claim_events_{column}"),
            "identity_link_claim_events",
            [column],
            unique=False,
        )


def _drop_event_indexes() -> None:
    for column in reversed(("actor_admin_id", "agent_id", "claim_id")):
        op.drop_index(
            op.f(f"ix_identity_link_claim_events_{column}"),
            table_name="identity_link_claim_events",
        )
    op.drop_index(
        "ix_identity_link_claim_event_claim_created",
        table_name="identity_link_claim_events",
    )
