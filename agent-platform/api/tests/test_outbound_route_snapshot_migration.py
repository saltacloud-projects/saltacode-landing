"""PostgreSQL migration coverage for immutable outbound route snapshots."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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

_REVISION = "f9d3e5a7b012"
_DOWN_REVISION = "f8c2d4e6a901"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_route_snapshot_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_quarantines_legacy_work_and_guards_snapshot_evidence() -> None:
    config = _config()
    ids = {key: uuid4() for key in _ID_KEYS}
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(_create_graph(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_insert_legacy_messages(ids))
        asyncio.run(engine.dispose())

        command.upgrade(config, "head")
        asyncio.run(_assert_legacy_disposition(ids))
        asyncio.run(engine.dispose())
        asyncio.run(_insert_snapshotted_message(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(DBAPIError, match="route snapshot is immutable"):
            asyncio.run(_mutate_snapshot(ids))
        asyncio.run(engine.dispose())
        with pytest.raises(DBAPIError, match="snapshots must be preserved"):
            command.downgrade(config, _DOWN_REVISION)
    finally:
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())


_ID_KEYS = (
    "agent",
    "connection",
    "route",
    "principal",
    "conversation",
    "queued",
    "dispatching",
    "accepted",
    "snapshotted",
)


async def _create_graph(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Outbound route snapshot agent",
            slug=f"outbound-route-snapshot-{uuid4().hex}",
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
            name="Outbound route snapshot connection",
            slug=f"outbound-route-snapshot-{uuid4().hex}",
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            version=0,
            external_account_id=f"snapshot-{uuid4().hex}",
            settings_json={},
            is_active=True,
        )
        principal = Principal(
            id=ids["principal"],
            display_name="Outbound route snapshot principal",
        )
        db.add_all([agent, connection, principal])
        await db.flush()
        route = ChannelAgentRoute(
            id=ids["route"],
            channel="whatsapp",
            version=0,
            route_key=f"outbound-route-snapshot-{uuid4().hex}",
            channel_connection_id=connection.id,
            agent_id=agent.id,
            is_active=True,
        )
        db.add(route)
        await db.flush()
        db.add(
            ChatConversation(
                id=ids["conversation"],
                agent_id=agent.id,
                automation_agent_id=agent.id,
                automation_version=0,
                principal_id=principal.id,
                channel="whatsapp",
                external_thread_id="5493870000000",
                route_key=route.route_key,
                channel_route_id=route.id,
                transcript_consent=True,
            )
        )
        await db.commit()


async def _insert_legacy_messages(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        statement = text(
            "INSERT INTO outbound_messages "
            "(id, conversation_id, agent_id, channel_route_id, kind, payload_json, "
            "destination, sender_type, control_version, automation_agent_id, "
            "automation_version, sequence, idempotency_key, payload_hash, "
            "correlation_id, status, provider_message_id, last_attempt_number, "
            "locked_by, locked_at) VALUES "
            "(:id, :conversation_id, :agent_id, :route_id, 'text', "
            "CAST(:payload AS jsonb), '5493870000000', 'automation', 0, "
            ":agent_id, 0, :sequence, :key, :hash, :correlation, :status, "
            ":provider_id, :attempt, :locked_by, :locked_at)"
        )
        rows = (
            ("queued", "queued", None, 0, None, None),
            (
                "dispatching",
                "dispatching",
                None,
                1,
                "legacy-worker",
                datetime.now(UTC),
            ),
            ("accepted", "accepted", "legacy-provider-id", 1, None, None),
        )
        for sequence, row in enumerate(rows, start=1):
            label, status, provider_id, attempt, locked_by, locked_at = row
            await db.execute(
                statement,
                {
                    "id": ids[label],
                    "conversation_id": ids["conversation"],
                    "agent_id": ids["agent"],
                    "route_id": ids["route"],
                    "payload": '{"text":"legacy"}',
                    "sequence": sequence,
                    "key": f"legacy-{label}",
                    "hash": label[0] * 64,
                    "correlation": f"legacy-{label}",
                    "status": status,
                    "provider_id": provider_id,
                    "attempt": attempt,
                    "locked_by": locked_by,
                    "locked_at": locked_at,
                },
            )
        await db.commit()


async def _assert_legacy_disposition(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        queued = await db.get(OutboundMessage, ids["queued"])
        dispatching = await db.get(OutboundMessage, ids["dispatching"])
        accepted = await db.get(OutboundMessage, ids["accepted"])
        assert queued is not None and queued.status == "cancelled"
        assert dispatching is not None and dispatching.status == "delivery_unknown"
        assert accepted is not None and accepted.status == "accepted"
        assert accepted.channel is None
        events = list(
            (
                await db.execute(
                    select(OutboundDeliveryEvent).where(
                        OutboundDeliveryEvent.outbound_message_id.in_(
                            [ids["queued"], ids["dispatching"]]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {event.safe_code for event in events} == {
            "legacy_route_snapshot_missing"
        }


async def _insert_snapshotted_message(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO outbound_messages "
                "(id, conversation_id, agent_id, channel_route_id, channel, "
                "adapter_key, channel_connection_id, route_version, "
                "connection_version, kind, payload_json, destination, sender_type, "
                "control_version, automation_agent_id, automation_version, sequence, "
                "idempotency_key, payload_hash, correlation_id, status, "
                "last_attempt_number) VALUES "
                "(:id, :conversation_id, :agent_id, :route_id, 'whatsapp', "
                "'meta_whatsapp_cloud', :connection_id, 0, 0, 'text', "
                "CAST(:payload AS jsonb), '5493870000000', 'automation', 0, "
                ":agent_id, 0, 4, 'snapshotted', :hash, 'snapshotted', 'queued', 0)"
            ),
            {
                "id": ids["snapshotted"],
                "conversation_id": ids["conversation"],
                "agent_id": ids["agent"],
                "route_id": ids["route"],
                "connection_id": ids["connection"],
                "payload": '{"text":"snapshot"}',
                "hash": "d" * 64,
            },
        )
        await db.commit()


async def _mutate_snapshot(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("UPDATE outbound_messages SET route_version = 1 WHERE id = :id"),
                {"id": ids["snapshotted"]},
            )
            await db.commit()
        finally:
            await db.rollback()


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OutboundMessage).where(
                OutboundMessage.id.in_(
                    [
                        ids["queued"],
                        ids["dispatching"],
                        ids["accepted"],
                        ids["snapshotted"],
                    ]
                )
            )
        )
        await db.execute(
            delete(ChatConversation).where(ChatConversation.id == ids["conversation"])
        )
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id == ids["route"])
        )
        await db.execute(
            delete(ChannelConnection).where(ChannelConnection.id == ids["connection"])
        )
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
