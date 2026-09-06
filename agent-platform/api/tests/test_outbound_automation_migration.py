"""PostgreSQL migration coverage for outbound acting-agent snapshots."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundDeliveryEvent, OutboundMessage
from app.models.platform import ChatConversation, Principal

_REVISION = "f4c8d0e2f567"
_DOWN_REVISION = "f3b7c9d1e456"
_HEAD_REVISION = "f13d7b9e1f45"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_outbound_automation_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_backfills_only_safe_legacy_commands_and_blocks_loss() -> None:
    config = _config()
    ids = {
        key: uuid4()
        for key in (
            "routing_agent",
            "acting_agent",
            "connection",
            "route",
            "safe_principal",
            "uncertain_principal",
            "safe_conversation",
            "uncertain_conversation",
            "safe_message",
            "uncertain_message",
        )
    }
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(_create_graph(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_insert_legacy_commands(ids))
        asyncio.run(engine.dispose())

        command.upgrade(config, "head")
        asyncio.run(_assert_migrated_commands(ids))
        asyncio.run(engine.dispose())

        asyncio.run(_make_snapshot_lossy(ids))
        asyncio.run(engine.dispose())
        with pytest.raises(DBAPIError, match="snapshots must be preserved"):
            command.downgrade(config, _DOWN_REVISION)
    finally:
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())


async def _create_graph(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        routing = AgentProfile(
            id=ids["routing_agent"],
            name="Outbound migration routing agent",
            slug=f"outbound-migration-routing-{uuid4().hex}",
            version=1,
            is_active=True,
            is_public=False,
            retention_days=30,
            prompt_identity="test",
            prompt_domain="test",
            prompt_guardrails="test",
            unauthorized_message="unauthorized",
            error_message="error",
        )
        acting = AgentProfile(
            id=ids["acting_agent"],
            name="Outbound migration acting agent",
            slug=f"outbound-migration-acting-{uuid4().hex}",
            version=1,
            is_active=True,
            is_public=False,
            retention_days=30,
            prompt_identity="test",
            prompt_domain="test",
            prompt_guardrails="test",
            unauthorized_message="unauthorized",
            error_message="error",
        )
        connection = ChannelConnection(
            id=ids["connection"],
            name="Outbound migration connection",
            slug=f"outbound-migration-{uuid4().hex}",
            channel="whatsapp",
            external_account_id=f"migration-{uuid4().hex}",
            settings_json={},
            is_active=True,
        )
        principals = [
            Principal(id=ids["safe_principal"], display_name="Safe legacy"),
            Principal(
                id=ids["uncertain_principal"],
                display_name="Uncertain legacy",
            ),
        ]
        db.add_all([routing, acting, connection, *principals])
        await db.flush()
        route = ChannelAgentRoute(
            id=ids["route"],
            channel="whatsapp",
            route_key=f"outbound-migration-{uuid4().hex}",
            channel_connection_id=connection.id,
            agent_id=routing.id,
            is_active=True,
        )
        db.add(route)
        await db.flush()
        db.add_all(
            [
                ChatConversation(
                    id=ids["safe_conversation"],
                    agent_id=routing.id,
                    automation_agent_id=routing.id,
                    automation_version=0,
                    principal_id=principals[0].id,
                    channel="whatsapp",
                    external_thread_id=f"safe-{uuid4().hex}",
                    route_key=route.route_key,
                    channel_route_id=route.id,
                    transcript_consent=True,
                ),
                ChatConversation(
                    id=ids["uncertain_conversation"],
                    agent_id=routing.id,
                    automation_agent_id=acting.id,
                    automation_version=1,
                    principal_id=principals[1].id,
                    channel="whatsapp",
                    external_thread_id=f"uncertain-{uuid4().hex}",
                    route_key=route.route_key,
                    channel_route_id=route.id,
                    transcript_consent=True,
                ),
            ]
        )
        await db.commit()


async def _insert_legacy_commands(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        statement = text(
            "INSERT INTO outbound_messages "
            "(id, conversation_id, agent_id, channel_route_id, kind, payload_json, "
            "destination, sender_type, control_version, sequence, idempotency_key, "
            "payload_hash, correlation_id, status, last_attempt_number) "
            "SELECT :message_id, id, agent_id, channel_route_id, 'text', "
            'CAST(\'{"text":"legacy"}\' AS jsonb), external_thread_id, '
            "'automation', 0, 1, :idempotency_key, :payload_hash, "
            ":correlation_id, 'queued', 0 FROM chat_conversations WHERE id = :conversation_id"
        )
        await db.execute(
            statement,
            {
                "message_id": ids["safe_message"],
                "conversation_id": ids["safe_conversation"],
                "idempotency_key": "safe-legacy",
                "payload_hash": "a" * 64,
                "correlation_id": "safe-legacy",
            },
        )
        await db.execute(
            statement,
            {
                "message_id": ids["uncertain_message"],
                "conversation_id": ids["uncertain_conversation"],
                "idempotency_key": "uncertain-legacy",
                "payload_hash": "b" * 64,
                "correlation_id": "uncertain-legacy",
            },
        )
        await db.commit()


async def _assert_migrated_commands(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        safe = await db.get(OutboundMessage, ids["safe_message"])
        uncertain = await db.get(OutboundMessage, ids["uncertain_message"])
        assert safe is not None
        assert safe.automation_agent_id == ids["routing_agent"]
        assert safe.automation_version == 0
        assert safe.status == "cancelled"
        route_event = (
            await db.execute(
                select(OutboundDeliveryEvent).where(
                    OutboundDeliveryEvent.outbound_message_id == safe.id,
                    OutboundDeliveryEvent.safe_code == "legacy_route_snapshot_missing",
                )
            )
        ).scalar_one()
        assert route_event.event_type == "cancelled"
        assert uncertain is not None
        assert uncertain.automation_agent_id is None
        assert uncertain.automation_version is None
        assert uncertain.status == "cancelled"
        event = (
            await db.execute(
                select(OutboundDeliveryEvent).where(
                    OutboundDeliveryEvent.outbound_message_id == uncertain.id,
                    OutboundDeliveryEvent.event_type == "cancelled",
                )
            )
        ).scalar_one()
        assert event.safe_code == "legacy_automation_unknown"


async def _make_snapshot_lossy(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        safe = await db.get(OutboundMessage, ids["safe_message"])
        assert safe is not None
        safe.automation_agent_id = ids["acting_agent"]
        safe.automation_version = 1
        await db.commit()


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OutboundMessage).where(
                OutboundMessage.id.in_([ids["safe_message"], ids["uncertain_message"]])
            )
        )
        await db.execute(
            delete(ChatConversation).where(
                ChatConversation.id.in_(
                    [ids["safe_conversation"], ids["uncertain_conversation"]]
                )
            )
        )
        await db.execute(
            delete(Principal).where(
                Principal.id.in_([ids["safe_principal"], ids["uncertain_principal"]])
            )
        )
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id == ids["route"])
        )
        await db.execute(
            delete(ChannelConnection).where(ChannelConnection.id == ids["connection"])
        )
        await db.execute(
            delete(AgentProfile).where(
                AgentProfile.id.in_([ids["routing_agent"], ids["acting_agent"]])
            )
        )
        await db.commit()
