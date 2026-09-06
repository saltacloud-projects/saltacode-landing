"""Add encrypted commercial contacts and append-only consent evidence.

Revision ID: 4c91b2f7e6a0
Revises: 8f813973069e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c91b2f7e6a0"
down_revision: str | None = "8f813973069e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("created_by_agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'provisional'"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("job_title", sa.String(length=160), nullable=True),
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
            "status IN ('provisional', 'active', 'archived')",
            name="ck_contact_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("principal_id", name="uq_contact_principal"),
    )
    op.create_index(
        op.f("ix_contacts_created_by_agent_id"),
        "contacts",
        ["created_by_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contacts_principal_id"),
        "contacts",
        ["principal_id"],
        unique=False,
    )

    op.create_table(
        "contact_points",
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("lookup_hmac", sa.String(length=64), nullable=False),
        sa.Column("masked_value", sa.String(length=255), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("source_channel_identity_id", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            "char_length(ciphertext) > 40 AND ciphertext <> masked_value",
            name="ck_contact_point_ciphertext",
        ),
        sa.CheckConstraint(
            "kind IN ('email', 'phone')",
            name="ck_contact_point_kind",
        ),
        sa.CheckConstraint(
            "char_length(lookup_hmac) = 64",
            name="ck_contact_point_lookup_hmac",
        ),
        sa.CheckConstraint(
            "verification_status != 'revoked' OR revoked_at IS NOT NULL",
            name="ck_contact_point_revoked_at",
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'pending', 'verified', 'revoked')",
            name="ck_contact_point_verification_status",
        ),
        sa.CheckConstraint(
            "verification_status != 'verified' OR verified_at IS NOT NULL",
            name="ck_contact_point_verified_at",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_channel_identity_id"],
            ["channel_identities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["chat_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contact_id",
            "kind",
            "lookup_hmac",
            name="uq_contact_point_value",
        ),
    )
    op.create_index(
        op.f("ix_contact_points_contact_id"),
        "contact_points",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_contact_point_kind_lookup",
        "contact_points",
        ["kind", "lookup_hmac"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_points_source_channel_identity_id"),
        "contact_points",
        ["source_channel_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contact_points_source_conversation_id"),
        "contact_points",
        ["source_conversation_id"],
        unique=False,
    )

    op.create_table(
        "consent_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("contact_point_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("source_channel_identity_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('grant', 'revoke')",
            name="ck_consent_record_action",
        ),
        sa.CheckConstraint(
            "char_length(command_hash) = 64",
            name="ck_consent_record_command_hash",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_consent_record_correlation",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > occurred_at",
            name="ck_consent_record_expiration",
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_consent_record_idempotency",
        ),
        sa.CheckConstraint(
            "char_length(btrim(locale)) > 0",
            name="ck_consent_record_locale",
        ),
        sa.CheckConstraint(
            "char_length(btrim(channel)) > 0",
            name="ck_consent_record_channel",
        ),
        sa.CheckConstraint(
            "char_length(btrim(policy_version)) > 0",
            name="ck_consent_record_policy_version",
        ),
        sa.CheckConstraint(
            "purpose IN ('conversation_storage', 'quote_delivery', "
            "'commercial_follow_up', 'marketing')",
            name="ck_consent_record_purpose",
        ),
        sa.CheckConstraint(
            "action != 'revoke' OR expires_at IS NULL",
            name="ck_consent_record_revoke_expiration",
        ),
        sa.CheckConstraint(
            "contact_point_id IS NULL OR contact_id IS NOT NULL",
            name="ck_consent_record_point_requires_contact",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["contact_point_id"],
            ["contact_points.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_channel_identity_id"],
            ["channel_identities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["chat_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_consent_record_agent_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_consent_records_agent_id"),
        "consent_records",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_contact_id"),
        "consent_records",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_contact_point_id"),
        "consent_records",
        ["contact_point_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_principal_id"),
        "consent_records",
        ["principal_id"],
        unique=False,
    )
    op.create_index(
        "ix_consent_record_effective",
        "consent_records",
        ["agent_id", "principal_id", "purpose", "contact_point_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_source_channel_identity_id"),
        "consent_records",
        ["source_channel_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_source_conversation_id"),
        "consent_records",
        ["source_conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_consent_records_source_conversation_id"),
        table_name="consent_records",
    )
    op.drop_index(
        op.f("ix_consent_records_source_channel_identity_id"),
        table_name="consent_records",
    )
    op.drop_index("ix_consent_record_effective", table_name="consent_records")
    op.drop_index(
        op.f("ix_consent_records_principal_id"),
        table_name="consent_records",
    )
    op.drop_index(
        op.f("ix_consent_records_contact_point_id"),
        table_name="consent_records",
    )
    op.drop_index(op.f("ix_consent_records_contact_id"), table_name="consent_records")
    op.drop_index(op.f("ix_consent_records_agent_id"), table_name="consent_records")
    op.drop_table("consent_records")

    op.drop_index(
        op.f("ix_contact_points_source_conversation_id"),
        table_name="contact_points",
    )
    op.drop_index(
        op.f("ix_contact_points_source_channel_identity_id"),
        table_name="contact_points",
    )
    op.drop_index("ix_contact_point_kind_lookup", table_name="contact_points")
    op.drop_index(op.f("ix_contact_points_contact_id"), table_name="contact_points")
    op.drop_table("contact_points")

    op.drop_index(op.f("ix_contacts_principal_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_created_by_agent_id"), table_name="contacts")
    op.drop_table("contacts")
