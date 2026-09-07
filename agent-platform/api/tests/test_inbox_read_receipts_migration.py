"""Upgrade/rollback and cross-session visibility proofs for operator receipts."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.inbox_read_receipt import InboxReadReceipt
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.services.inbox_visibility import mark_inbox_messages_read
from app.services.operator_inbox import operator_inbox_service

REVISION = "f15f9d1a3b67"
PREVIOUS = "f14e8c0f2a56"


def config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic-platform.ini"))


def test_inbox_read_receipts_revision_is_additive_single_head():
    script = ScriptDirectory.from_config(config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


async def seed(ids):
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Receipt migration",
            slug=f"receipt-{ids['agent']}",
            prompt_identity="Test",
            prompt_domain="Test",
            prompt_guardrails="Test",
            unauthorized_message="Unavailable",
            error_message="Unavailable",
        )
        principal = Principal(id=ids["principal"], display_name="Synthetic")
        role = AdminRole(
            key=ids["role"],
            name="Receipt migration",
            permissions=["conversations.read"],
        )
        db.add_all([agent, principal, role])
        await db.flush()
        db.add(
            AdminUser(
                id=ids["admin"],
                name="Receipt operator",
                email=f"{ids['admin']}@example.invalid",
                hashed_password="not-a-login",
                role=role.key,
            )
        )
        db.add(
            ChatConversation(
                id=ids["conversation"],
                agent_id=agent.id,
                automation_agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                route_key="receipt-migration",
                external_thread_id=str(ids["conversation"]),
            )
        )
        await db.flush()
        db.add(
            ChatMessage(
                id=ids["message"],
                conversation_id=ids["conversation"],
                role="user",
                content="Synthetic retained transcript",
                client_message_id=str(ids["message"]),
            )
        )
        await db.commit()
    await engine.dispose()


async def verify_and_acknowledge(ids):
    kwargs = dict(
        agent_id=ids["agent"],
        conversation_id=ids["conversation"],
        admin_user_id=ids["admin"],
    )
    async with AsyncSessionLocal() as reader:
        assert (
            await reader.execute(select(func.count()).select_from(InboxReadReceipt))
        ).scalar_one() == 0
        displayed = await operator_inbox_service.get_thread(reader, **kwargs)
        assert displayed.messages[0].content == "Synthetic retained transcript"
        async with AsyncSessionLocal() as writer:
            writer.add(
                ChatMessage(
                    conversation_id=ids["conversation"],
                    role="user",
                    content="Late committed inbound",
                    client_message_id=uuid4().hex,
                    created_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            await writer.commit()
        assert (
            await mark_inbox_messages_read(
                reader, **kwargs, message_ids=[item.id for item in displayed.messages]
            )
            == 1
        )
        await reader.commit()
    async with AsyncSessionLocal() as reloaded:
        assert (
            await operator_inbox_service.get_thread(reloaded, **kwargs)
        ).conversation.unread_count == 1
    await engine.dispose()


async def cleanup(ids):
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ChatConversation).where(ChatConversation.id == ids["conversation"])
        )
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(delete(AdminUser).where(AdminUser.id == ids["admin"]))
        await db.execute(delete(AdminRole).where(AdminRole.key == ids["role"]))
        await db.commit()
    await engine.dispose()


@pytest.mark.integration
def test_prior_upgrade_preserves_transcripts_without_read_backfill_and_blocks_lossy_rollback():
    cfg = config()
    ids = {
        name: uuid4()
        for name in ("agent", "principal", "conversation", "admin", "message")
    }
    ids["role"] = f"receipt-{uuid4().hex[:20]}"
    asyncio.run(engine.dispose())
    try:
        command.downgrade(cfg, PREVIOUS)
        asyncio.run(seed(ids))
        command.upgrade(cfg, REVISION)
        asyncio.run(verify_and_acknowledge(ids))
        with pytest.raises(
            RuntimeError, match="Cannot discard persisted operator read receipts"
        ):
            command.downgrade(cfg, PREVIOUS)
    finally:
        command.upgrade(cfg, REVISION)
        asyncio.run(cleanup(ids))
    command.downgrade(cfg, PREVIOUS)
    command.upgrade(cfg, REVISION)
    command.check(cfg)
    asyncio.run(engine.dispose())
