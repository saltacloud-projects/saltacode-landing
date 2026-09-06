"""Migration coverage for channel adapter identity and CAS versions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.database import engine

_REVISION = "f7b1c3d5e890"
_DOWN_REVISION = "f6a0b2c4d789"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


async def _insert_legacy_channel_rows() -> tuple[UUID, UUID, UUID, UUID]:
    profile_id = uuid4()
    web_id = uuid4()
    whatsapp_id = uuid4()
    route_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO agent_profiles ("
                "id, name, slug, version, is_active, is_public, retention_days, "
                "prompt_identity, prompt_domain, prompt_guardrails, "
                "unauthorized_message, error_message"
                ") VALUES ("
                ":id, :name, :slug, 1, true, false, 30, "
                "'identity', 'domain', 'guardrails', 'unauthorized', 'error'"
                ")"
            ),
            {
                "id": profile_id,
                "name": "Channel migration profile",
                "slug": f"channel-migration-{profile_id.hex[:8]}",
            },
        )
        for connection_id, channel in (
            (web_id, "web"),
            (whatsapp_id, "whatsapp"),
        ):
            await connection.execute(
                text(
                    "INSERT INTO channel_connections ("
                    "id, name, slug, channel, settings, is_active"
                    ") VALUES ("
                    ":id, :name, :slug, :channel, '{}'::jsonb, true"
                    ")"
                ),
                {
                    "id": connection_id,
                    "name": f"Legacy {channel}",
                    "slug": f"legacy-{channel}-{connection_id.hex[:8]}",
                    "channel": channel,
                },
            )
        await connection.execute(
            text(
                "INSERT INTO channel_agent_routes ("
                "id, channel, route_key, channel_connection_id, agent_id, is_active"
                ") VALUES ("
                ":id, 'web', :route_key, :connection_id, :agent_id, true"
                ")"
            ),
            {
                "id": route_id,
                "route_key": f"legacy-route-{route_id.hex}",
                "connection_id": web_id,
                "agent_id": profile_id,
            },
        )
    return profile_id, web_id, whatsapp_id, route_id


async def _channel_rows(web_id: UUID, whatsapp_id: UUID, route_id: UUID):
    async with engine.connect() as connection:
        connections = (
            await connection.execute(
                text(
                    "SELECT id, adapter_key, version FROM channel_connections "
                    "WHERE id IN (:web_id, :whatsapp_id) ORDER BY adapter_key"
                ),
                {"web_id": web_id, "whatsapp_id": whatsapp_id},
            )
        ).all()
        route_version = (
            await connection.execute(
                text("SELECT version FROM channel_agent_routes WHERE id = :route_id"),
                {"route_id": route_id},
            )
        ).scalar_one()
    return connections, route_version


async def _legacy_writer_insert_uses_canonical_adapter() -> tuple[UUID, str]:
    connection_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO channel_connections ("
                "id, name, slug, channel, settings, is_active"
                ") VALUES ("
                ":id, 'Legacy writer web', :slug, 'web', '{}'::jsonb, true"
                ")"
            ),
            {
                "id": connection_id,
                "slug": f"legacy-writer-web-{connection_id.hex[:8]}",
            },
        )
        adapter_key = (
            await connection.execute(
                text("SELECT adapter_key FROM channel_connections WHERE id = :id"),
                {"id": connection_id},
            )
        ).scalar_one()
    return connection_id, adapter_key


async def _delete_channel_rows(
    profile_id: UUID,
    web_id: UUID,
    whatsapp_id: UUID,
    legacy_writer_id: UUID,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM channel_agent_routes WHERE channel_connection_id IN "
                "(:web_id, :whatsapp_id)"
            ),
            {"web_id": web_id, "whatsapp_id": whatsapp_id},
        )
        await connection.execute(
            text(
                "DELETE FROM channel_connections WHERE id IN "
                "(:web_id, :whatsapp_id, :legacy_writer_id)"
            ),
            {
                "web_id": web_id,
                "whatsapp_id": whatsapp_id,
                "legacy_writer_id": legacy_writer_id,
            },
        )
        await connection.execute(
            text("DELETE FROM agent_profiles WHERE id = :profile_id"),
            {"profile_id": profile_id},
        )


def test_channel_catalog_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_channel_catalog_migration_backfills_and_round_trips() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        profile_id, web_id, whatsapp_id, route_id = asyncio.run(
            _insert_legacy_channel_rows()
        )
        asyncio.run(engine.dispose())
        command.upgrade(config, _REVISION)
        rows, route_version = asyncio.run(_channel_rows(web_id, whatsapp_id, route_id))
        asyncio.run(engine.dispose())
        legacy_writer_id, legacy_writer_adapter = asyncio.run(
            _legacy_writer_insert_uses_canonical_adapter()
        )
        asyncio.run(engine.dispose())

        assert {(row.adapter_key, row.version) for row in rows} == {
            ("web_builtin", 0),
            ("meta_whatsapp_cloud", 0),
        }
        assert route_version == 0
        assert legacy_writer_adapter == "web_builtin"

        asyncio.run(
            _delete_channel_rows(
                profile_id,
                web_id,
                whatsapp_id,
                legacy_writer_id,
            )
        )
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, _REVISION)
        command.check(config)
    finally:
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())
