"""Revision and rollback coverage for resumable web execution persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal

_REVISION = "f3b7c9d1e456"
_DOWN_REVISION = "f2a6b8c0d345"
_HEAD_REVISION = "f5d9e1f3a678"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_resumable_web_execution_migration_is_the_single_head():
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION
    assert scripts.get_revision("8f813973069e").down_revision == "7e702862958d"


@pytest.mark.integration
def test_resumable_web_execution_migration_downgrades_and_upgrades_cleanly():
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, "7e702862958d")
    finally:
        command.upgrade(config, "head")
    command.check(config)
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_execution_snapshot_migration_backfills_and_blocks_lossy_downgrade():
    config = _config()
    ids = {
        "agent": uuid4(),
        "conversation": uuid4(),
        "execution": uuid4(),
        "message": uuid4(),
        "principal": uuid4(),
    }
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(_create_conversation(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_create_pre_snapshot_execution(ids))
        asyncio.run(engine.dispose())
        command.upgrade(config, "head")
        asyncio.run(_assert_snapshot_backfilled(ids))
        asyncio.run(engine.dispose())
        asyncio.run(_advance_conversation_automation(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(DBAPIError, match="snapshots must be preserved"):
            command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, "head")
        command.check(config)
    finally:
        command.upgrade(config, "head")
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())


async def _create_conversation(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Execution migration agent",
            slug=f"execution-migration-{uuid4().hex}",
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
        principal = Principal(id=ids["principal"], display_name="Migration lead")
        db.add_all([agent, principal])
        await db.flush()
        db.add(
            ChatConversation(
                id=ids["conversation"],
                agent_id=agent.id,
                automation_agent_id=agent.id,
                automation_version=3,
                principal_id=principal.id,
                channel="web",
                external_thread_id=f"migration-{uuid4().hex}",
                route_key=f"migration-{uuid4().hex}",
                transcript_consent=True,
            )
        )
        await db.commit()


async def _create_pre_snapshot_execution(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO chat_messages "
                "(id, conversation_id, client_message_id, role, content, status, "
                "tool_names, metadata_json) "
                "VALUES (:message, :conversation, 'migration-input', 'user', "
                "'hello', 'completed', CAST('[]' AS jsonb), CAST('{}' AS jsonb))"
            ),
            ids,
        )
        await db.execute(
            text(
                "INSERT INTO chat_executions "
                "(id, request_id, conversation_id, inbound_message_id, status, "
                "control_version, tools_used, usage, attempt_count) "
                "VALUES (:execution, 'migration-execution', :conversation, :message, "
                "'completed', 0, CAST('[]' AS jsonb), CAST('{}' AS jsonb), 0)"
            ),
            ids,
        )
        await db.commit()


async def _assert_snapshot_backfilled(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        execution = await db.get(ChatExecution, ids["execution"])
        assert execution is not None
        assert execution.automation_agent_id == ids["agent"]
        assert execution.automation_version == 3


async def _advance_conversation_automation(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        conversation = await db.get(ChatConversation, ids["conversation"])
        assert conversation is not None
        conversation.automation_version = 4
        await db.commit()


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ChatExecution).where(ChatExecution.id == ids["execution"])
        )
        await db.execute(delete(ChatMessage).where(ChatMessage.id == ids["message"]))
        await db.execute(
            delete(ChatConversation).where(ChatConversation.id == ids["conversation"])
        )
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
