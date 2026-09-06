"""Migration coverage for fail-closed outbound delivery resolution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundDeliveryResolution, OutboundMessage
from app.models.platform import ChatConversation, Principal

_REVISION = "f13d7b9e1f45"
_DOWN_REVISION = "f12c6a8d0e34"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_delivery_resolution_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_resolution_migration_defaults_existing_rows_and_blocks_evidence_loss() -> None:
    config = _config()
    ids = asyncio.run(_insert_graph())
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, _REVISION)
        asyncio.run(engine.dispose())
        assert asyncio.run(_resolution_version(ids["message"])) == 0
        asyncio.run(engine.dispose())
        asyncio.run(_insert_resolution(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(RuntimeError, match="resolution evidence must be preserved"):
            command.downgrade(config, _DOWN_REVISION)
        asyncio.run(engine.dispose())
        asyncio.run(_delete_resolution(ids["message"]))
        asyncio.run(engine.dispose())

        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, _REVISION)
    finally:
        asyncio.run(engine.dispose())
        command.upgrade(config, "head")
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())


async def _insert_graph() -> dict[str, object]:
    async with AsyncSessionLocal() as db:
        admin = (
            (await db.execute(select(AdminUser).where(AdminUser.is_active.is_(True))))
            .scalars()
            .first()
        )
        assert admin is not None
        agent = AgentProfile(
            name="Delivery resolution migration agent",
            slug=f"delivery-resolution-migration-{uuid4().hex}",
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
            name="Delivery resolution migration connection",
            slug=f"delivery-resolution-migration-{uuid4().hex}",
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            version=0,
            external_account_id=f"delivery-resolution-migration-{uuid4().hex}",
            settings_json={},
            is_active=True,
        )
        principal = Principal()
        db.add_all([agent, connection, principal])
        await db.flush()
        route = ChannelAgentRoute(
            channel="whatsapp",
            route_key=f"delivery-resolution-migration-{uuid4().hex}",
            channel_connection_id=connection.id,
            agent_id=agent.id,
            version=0,
            is_active=True,
        )
        db.add(route)
        await db.flush()
        conversation = ChatConversation(
            agent_id=agent.id,
            automation_agent_id=agent.id,
            automation_version=0,
            principal_id=principal.id,
            channel="whatsapp",
            external_thread_id=f"delivery-resolution-migration-{uuid4().hex}",
            route_key=route.route_key,
            channel_route_id=route.id,
            status="active",
            control_mode="automated",
            control_version=0,
        )
        db.add(conversation)
        await db.flush()
        message = OutboundMessage(
            conversation_id=conversation.id,
            agent_id=agent.id,
            channel_route_id=route.id,
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            channel_connection_id=connection.id,
            route_version=0,
            connection_version=0,
            kind="text",
            payload_json={"text": "migration evidence"},
            destination="migration-destination",
            sender_type="automation",
            control_version=0,
            automation_agent_id=agent.id,
            automation_version=0,
            sequence=1,
            idempotency_key=f"migration-{uuid4().hex}",
            payload_hash="a" * 64,
            correlation_id="delivery-resolution-migration",
            status="delivery_unknown",
            last_attempt_number=0,
            resolution_version=0,
        )
        db.add(message)
        await db.commit()
        return {
            "admin": admin.id,
            "agent": agent.id,
            "connection": connection.id,
            "route": route.id,
            "principal": principal.id,
            "message": message.id,
        }


async def _resolution_version(message_id) -> int:
    async with AsyncSessionLocal() as db:
        value = (
            await db.execute(
                select(OutboundMessage.resolution_version).where(
                    OutboundMessage.id == message_id
                )
            )
        ).scalar_one()
        return int(value)


async def _insert_resolution(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            OutboundDeliveryResolution(
                outbound_message_id=ids["message"],
                resolution_version=1,
                action="confirm_not_delivered",
                provider_message_hash=None,
                provider_message_suffix=None,
                evidence_source=None,
                reason_code="provider_record_not_found",
                actor_admin_id=ids["admin"],
                idempotency_key="migration-resolution",
                command_hash="b" * 64,
                correlation_id="migration-resolution",
            )
        )
        await db.commit()


async def _delete_resolution(message_id) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OutboundDeliveryResolution).where(
                OutboundDeliveryResolution.outbound_message_id == message_id
            )
        )
        await db.commit()


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id == ids["route"])
        )
        await db.execute(
            delete(ChannelConnection).where(ChannelConnection.id == ids["connection"])
        )
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
