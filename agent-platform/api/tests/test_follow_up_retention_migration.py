"""PostgreSQL migration coverage for retained follow-up evidence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
from app.models.contact import ConsentRecord, Contact
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity
from app.models.platform import ChatConversation, Principal

_REVISION = "f11b5f7c9d23"
_HEAD_REVISION = "f12c6a8d0e34"
_DOWN_REVISION = "f10a4e6b8c12"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_follow_up_retention_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_backfills_source_and_blocks_retained_evidence_loss() -> None:
    config = _config()
    ids = {
        key: uuid4()
        for key in (
            "agent",
            "principal",
            "conversation",
            "contact",
            "consent",
            "opportunity",
            "task",
        )
    }
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_insert_f10_graph(ids))
        asyncio.run(engine.dispose())

        command.upgrade(config, _REVISION)
        asyncio.run(_assert_backfill_and_detach(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(DBAPIError, match="follow-up retention evidence"):
            command.downgrade(config, _DOWN_REVISION)
    finally:
        asyncio.run(engine.dispose())
        command.upgrade(config, "head")
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())


async def _insert_f10_graph(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Retention migration agent",
            slug=f"retention-migration-{uuid4().hex}",
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
        principal = Principal(id=ids["principal"])
        db.add_all([agent, principal])
        await db.flush()
        conversation = ChatConversation(
            id=ids["conversation"],
            agent_id=agent.id,
            automation_agent_id=agent.id,
            principal_id=principal.id,
            channel="web",
            external_thread_id=f"retention-{uuid4().hex}",
            route_key=f"retention-{uuid4().hex}",
            status="active",
            control_mode="automated",
        )
        contact = Contact(
            id=ids["contact"],
            principal_id=principal.id,
            created_by_agent_id=agent.id,
            status="active",
        )
        db.add_all([conversation, contact])
        await db.flush()
        consent = ConsentRecord(
            id=ids["consent"],
            principal_id=principal.id,
            contact_id=contact.id,
            contact_point_id=None,
            agent_id=agent.id,
            purpose="commercial_follow_up",
            action="grant",
            policy_version="migration-v1",
            channel="web",
            locale="en",
            source_conversation_id=conversation.id,
            correlation_id="retention-migration-consent",
            idempotency_key="retention-migration-consent",
            command_hash="a" * 64,
            occurred_at=datetime.now(UTC),
        )
        opportunity = Opportunity(
            id=ids["opportunity"],
            contact_id=contact.id,
            created_by_agent_id=agent.id,
            assigned_agent_id=agent.id,
            stage="qualified",
            control_version=0,
            title="Retention migration",
            correlation_id="retention-migration-opportunity",
            idempotency_key="retention-migration-opportunity",
            command_hash="b" * 64,
        )
        db.add_all([consent, opportunity])
        await db.flush()
        await db.execute(
            text(
                "INSERT INTO follow_up_tasks ("
                "id, opportunity_id, conversation_id, consent_record_id, "
                "assigned_agent_id, kind, status, state_version, due_at, "
                "available_at, attempts, max_attempts, correlation_id, "
                "idempotency_key, command_hash, completed_at"
                ") VALUES ("
                ":id, :opportunity_id, :conversation_id, :consent_id, :agent_id, "
                "'commercial_follow_up', 'completed', 0, :occurred_at, "
                ":occurred_at, 0, 3, 'retention-migration-task', "
                "'retention-migration-task', :command_hash, :occurred_at"
                ")"
            ),
            {
                "id": ids["task"],
                "opportunity_id": ids["opportunity"],
                "conversation_id": ids["conversation"],
                "consent_id": ids["consent"],
                "agent_id": ids["agent"],
                "occurred_at": datetime.now(UTC),
                "command_hash": "c" * 64,
            },
        )
        await db.commit()


async def _assert_backfill_and_detach(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, ids["task"])
        assert task is not None
        assert task.source_conversation_id == ids["conversation"]
        assert task.had_chat_message_evidence is False
        assert task.had_outbound_message_evidence is False
        task.conversation_id = None
        task.had_outbound_message_evidence = True
        await db.commit()


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FollowUpTaskEvent).where(FollowUpTaskEvent.task_id == ids["task"])
        )
        await db.execute(delete(FollowUpTask).where(FollowUpTask.id == ids["task"]))
        await db.execute(
            delete(Opportunity).where(Opportunity.id == ids["opportunity"])
        )
        await db.execute(
            delete(ConsentRecord).where(ConsentRecord.id == ids["consent"])
        )
        await db.execute(delete(Contact).where(Contact.id == ids["contact"]))
        await db.execute(
            delete(ChatConversation).where(ChatConversation.id == ids["conversation"])
        )
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
