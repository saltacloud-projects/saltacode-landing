"""scope authorized users and neutral chat identities by agent route

Revision ID: b7e4a1c2d930
Revises: a31e4d8b27f0
Create Date: 2026-08-27 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "b7e4a1c2d930"
down_revision: str | None = "a31e4d8b27f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_default_agent_for_existing_users(default_slug: str) -> None:
    bind = op.get_bind()
    has_users = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM authorized_users)"))
    if not has_users.scalar():
        return
    default_agent = bind.execute(
        sa.text("SELECT id FROM agent_profiles WHERE slug = :slug"),
        {"slug": default_slug},
    ).scalar_one_or_none()
    if default_agent is None:
        raise RuntimeError(
            "Cannot backfill authorized users: DEFAULT_AGENT_SLUG does not exist"
        )


def _create_agent_access_tables() -> None:
    op.create_table(
        "agent_authorized_user_bindings",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "has_all_area_access",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
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
            ["user_id"], ["authorized_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id", "user_id", name="uq_agent_authorized_user_binding"
        ),
    )
    op.create_index(
        "ix_agent_authorized_user_bindings_agent_id",
        "agent_authorized_user_bindings",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_authorized_user_bindings_user_id",
        "agent_authorized_user_bindings",
        ["user_id"],
    )

    op.create_table(
        "agent_authorized_user_areas",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("area_id", sa.UUID(), nullable=False),
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
            ["agent_id", "area_id"],
            [
                "agent_organization_area_bindings.agent_id",
                "agent_organization_area_bindings.area_id",
            ],
            name="fk_agent_authorized_user_area_area",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "user_id"],
            [
                "agent_authorized_user_bindings.agent_id",
                "agent_authorized_user_bindings.user_id",
            ],
            name="fk_agent_authorized_user_area_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "user_id",
            "area_id",
            name="uq_agent_authorized_user_area",
        ),
    )
    for column in ("agent_id", "user_id", "area_id"):
        op.create_index(
            f"ix_agent_authorized_user_areas_{column}",
            "agent_authorized_user_areas",
            [column],
        )


def _backfill_agent_access(default_slug: str) -> None:
    op.execute(
        sa.text("""
            INSERT INTO agent_authorized_user_bindings (
                id, agent_id, user_id, is_active, has_all_area_access
            )
            SELECT
                gen_random_uuid(), profile.id, users.id,
                users.is_active, users.has_all_area_access
            FROM agent_profiles AS profile
            CROSS JOIN authorized_users AS users
            WHERE profile.slug = :default_slug
            ON CONFLICT (agent_id, user_id) DO NOTHING
        """).bindparams(
            sa.bindparam("default_slug", default_slug, literal_execute=True)
        )
    )
    op.execute(
        sa.text("""
            INSERT INTO agent_authorized_user_areas (
                id, agent_id, user_id, area_id
            )
            SELECT
                gen_random_uuid(), binding.agent_id, binding.user_id, legacy.area_id
            FROM agent_authorized_user_bindings AS binding
            JOIN agent_profiles AS profile ON profile.id = binding.agent_id
            JOIN authorized_user_areas AS legacy ON legacy.user_id = binding.user_id
            JOIN agent_organization_area_bindings AS owned_area
              ON owned_area.agent_id = binding.agent_id
             AND owned_area.area_id = legacy.area_id
            WHERE profile.slug = :default_slug
            ON CONFLICT (agent_id, user_id, area_id) DO NOTHING
        """).bindparams(
            sa.bindparam("default_slug", default_slug, literal_execute=True)
        )
    )


def _scope_neutral_chat(default_scope: str) -> None:
    op.execute(
        sa.text("""
        UPDATE chat_conversations AS conversation
        SET route_key = profile.slug
        FROM agent_profiles AS profile
        WHERE conversation.agent_id = profile.id
          AND conversation.route_key IS NULL
    """)
    )
    op.alter_column(
        "chat_conversations",
        "route_key",
        existing_type=sa.String(length=120),
        nullable=False,
    )
    op.drop_constraint(
        "uq_chat_conversation_external_thread",
        "chat_conversations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_chat_conversation_external_thread",
        "chat_conversations",
        ["agent_id", "channel", "route_key", "external_thread_id"],
    )

    op.add_column(
        "channel_identities", sa.Column("route_key", sa.String(120), nullable=True)
    )
    op.drop_constraint(
        "uq_channel_identity_subject", "channel_identities", type_="unique"
    )
    op.execute(
        sa.text("""
            UPDATE channel_identities AS identity
            SET route_key = COALESCE(
                (
                    SELECT min(conversation.route_key)
                    FROM chat_conversations AS conversation
                    WHERE conversation.principal_id = identity.principal_id
                      AND conversation.channel = identity.channel
                      AND conversation.external_thread_id = identity.external_subject
                ),
                :default_scope
            )
        """).bindparams(
            sa.bindparam("default_scope", default_scope, literal_execute=True)
        )
    )
    op.execute(
        sa.text("""
        INSERT INTO channel_identities (
            id, principal_id, channel, route_key, external_subject,
            verified, attributes, created_at, updated_at
        )
        SELECT DISTINCT ON (
            identity.principal_id,
            identity.channel,
            identity.external_subject,
            conversation.route_key
        )
            gen_random_uuid(), identity.principal_id, identity.channel,
            conversation.route_key, identity.external_subject,
            identity.verified, identity.attributes, identity.created_at, identity.updated_at
        FROM channel_identities AS identity
        JOIN chat_conversations AS conversation
          ON conversation.principal_id = identity.principal_id
         AND conversation.channel = identity.channel
         AND conversation.external_thread_id = identity.external_subject
        WHERE conversation.route_key <> identity.route_key
    """)
    )
    op.alter_column(
        "channel_identities",
        "route_key",
        existing_type=sa.String(length=120),
        nullable=False,
    )
    op.create_index(
        "ix_channel_identities_route_key", "channel_identities", ["route_key"]
    )
    op.create_unique_constraint(
        "uq_channel_identity_subject",
        "channel_identities",
        ["channel", "route_key", "external_subject"],
    )


def upgrade() -> None:
    default_slug = settings.default_agent_slug.strip()
    if not default_slug:
        raise RuntimeError("DEFAULT_AGENT_SLUG is required for access backfill")
    _require_default_agent_for_existing_users(default_slug)
    _create_agent_access_tables()
    _backfill_agent_access(default_slug)
    _scope_neutral_chat(default_slug)


def _guard_downgrade_against_route_data_loss() -> None:
    bind = op.get_bind()
    conversation_conflict = bind.execute(
        sa.text("""
        SELECT EXISTS (
            SELECT 1
            FROM chat_conversations
            GROUP BY agent_id, channel, external_thread_id
            HAVING count(*) > 1
        )
    """)
    ).scalar()
    identity_conflict = bind.execute(
        sa.text("""
        SELECT EXISTS (
            SELECT 1
            FROM channel_identities
            GROUP BY channel, external_subject
            HAVING count(*) > 1
        )
    """)
    ).scalar()
    if conversation_conflict or identity_conflict:
        raise RuntimeError("Downgrade would merge route-scoped chat data")


def downgrade() -> None:
    _guard_downgrade_against_route_data_loss()

    op.drop_constraint(
        "uq_channel_identity_subject", "channel_identities", type_="unique"
    )
    op.drop_index("ix_channel_identities_route_key", table_name="channel_identities")
    op.drop_column("channel_identities", "route_key")
    op.create_unique_constraint(
        "uq_channel_identity_subject",
        "channel_identities",
        ["channel", "external_subject"],
    )

    op.drop_constraint(
        "uq_chat_conversation_external_thread",
        "chat_conversations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_chat_conversation_external_thread",
        "chat_conversations",
        ["agent_id", "channel", "external_thread_id"],
    )
    op.alter_column(
        "chat_conversations",
        "route_key",
        existing_type=sa.String(length=120),
        nullable=True,
    )

    op.drop_table("agent_authorized_user_areas")
    op.drop_table("agent_authorized_user_bindings")
