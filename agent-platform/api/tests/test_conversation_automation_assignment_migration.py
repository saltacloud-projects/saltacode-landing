"""Revision and rollback coverage for automation assignment persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.platform import ChatConversation, Principal
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentService,
)

_REVISION = "f2a6b8c0d345"
_DOWN_REVISION = "e1f5a7b9c234"
_HEAD_REVISION = "f3b7c9d1e456"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_automation_assignment_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_backfills_existing_conversations_and_round_trips() -> None:
    config = _config()
    agent_id = uuid4()
    principal_id = uuid4()
    conversation_id = uuid4()
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(
            _create_existing_conversation(
                agent_id=agent_id,
                principal_id=principal_id,
                conversation_id=conversation_id,
            )
        )
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_assert_assignment_columns_absent())

        command.upgrade(config, "head")
        asyncio.run(
            _assert_backfilled_and_cleanup(
                agent_id=agent_id,
                principal_id=principal_id,
                conversation_id=conversation_id,
            )
        )
        command.check(config)
    finally:
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())


@pytest.mark.integration
def test_migration_blocks_downgrade_that_would_discard_assignment_history() -> None:
    config = _config()
    routing_agent_id = uuid4()
    target_agent_id = uuid4()
    principal_id = uuid4()
    conversation_id = uuid4()
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(
            _create_assignment_history(
                routing_agent_id=routing_agent_id,
                target_agent_id=target_agent_id,
                principal_id=principal_id,
                conversation_id=conversation_id,
            )
        )
        with pytest.raises(DBAPIError, match="assignment history must be preserved"):
            command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_assert_current_revision(_HEAD_REVISION))
    finally:
        command.upgrade(config, "head")
        asyncio.run(
            _cleanup_assignment_history(
                routing_agent_id=routing_agent_id,
                target_agent_id=target_agent_id,
                principal_id=principal_id,
                conversation_id=conversation_id,
            )
        )
        asyncio.run(engine.dispose())


async def _create_existing_conversation(
    *,
    agent_id: UUID,
    principal_id: UUID,
    conversation_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            agent = AgentProfile(
                id=agent_id,
                name="Automation migration agent",
                slug=f"automation-migration-{agent_id.hex}",
                version=1,
                is_active=True,
                is_public=False,
                retention_days=30,
                prompt_identity="Identity",
                prompt_domain="Domain",
                prompt_guardrails="Guardrails",
                unauthorized_message="Unauthorized",
                error_message="Error",
                created_by="migration-test",
            )
            principal = Principal(
                id=principal_id,
                kind="anonymous",
                is_active=True,
                attributes={},
            )
            db.add_all([agent, principal])
            await db.flush()
            db.add(
                ChatConversation(
                    id=conversation_id,
                    agent_id=agent_id,
                    principal_id=principal_id,
                    channel="web",
                    external_thread_id=f"migration-{conversation_id}",
                    route_key=f"migration-{conversation_id.hex}",
                    status="active",
                    control_mode="automated",
                    control_version=0,
                    next_outbound_sequence=1,
                    next_event_sequence=1,
                    transcript_consent=False,
                    attributes={},
                )
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _create_assignment_history(
    *,
    routing_agent_id: UUID,
    target_agent_id: UUID,
    principal_id: UUID,
    conversation_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            routing = AgentProfile(
                id=routing_agent_id,
                name="Automation history routing agent",
                slug=f"automation-history-routing-{routing_agent_id.hex}",
                version=1,
                is_active=True,
                is_public=False,
                retention_days=30,
                prompt_identity="Identity",
                prompt_domain="Domain",
                prompt_guardrails="Guardrails",
                unauthorized_message="Unauthorized",
                error_message="Error",
                created_by="migration-test",
            )
            target = AgentProfile(
                id=target_agent_id,
                name="Automation history target agent",
                slug=f"automation-history-target-{target_agent_id.hex}",
                version=1,
                is_active=True,
                is_public=False,
                retention_days=30,
                prompt_identity="Identity",
                prompt_domain="Domain",
                prompt_guardrails="Guardrails",
                unauthorized_message="Unauthorized",
                error_message="Error",
                created_by="migration-test",
            )
            principal = Principal(
                id=principal_id,
                kind="anonymous",
                is_active=True,
                attributes={},
            )
            db.add_all([routing, target, principal])
            await db.flush()
            conversation = ChatConversation(
                id=conversation_id,
                agent_id=routing_agent_id,
                principal_id=principal_id,
                channel="web",
                external_thread_id=f"history-{conversation_id}",
                route_key=f"history-{conversation_id.hex}",
                status="active",
                control_mode="automated",
                control_version=0,
                next_outbound_sequence=1,
                next_event_sequence=1,
                transcript_consent=False,
                attributes={},
            )
            db.add(conversation)
            await db.flush()
            await ConversationAutomationAssignmentService().assign(
                db,
                conversation_id=conversation_id,
                routing_agent_id=routing_agent_id,
                target_agent_id=target_agent_id,
                expected_automation_version=0,
                actor_agent_id=routing_agent_id,
                actor_admin_id=None,
                trigger="migration_test",
                opportunity_id=None,
                correlation_id="migration-history",
                idempotency_key="migration-history",
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _assert_current_revision(expected_revision: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            revision = (
                await db.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == expected_revision
    finally:
        await engine.dispose()


async def _cleanup_assignment_history(
    *,
    routing_agent_id: UUID,
    target_agent_id: UUID,
    principal_id: UUID,
    conversation_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ConversationAutomationAssignmentEvent).where(
                    ConversationAutomationAssignmentEvent.conversation_id
                    == conversation_id
                )
            )
            await db.execute(
                delete(ChatConversation).where(ChatConversation.id == conversation_id)
            )
            await db.execute(delete(Principal).where(Principal.id == principal_id))
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_([routing_agent_id, target_agent_id])
                )
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _assert_assignment_columns_absent() -> None:
    try:
        async with AsyncSessionLocal() as db:
            columns = set(
                (
                    await db.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'chat_conversations'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "automation_agent_id" not in columns
            assert "automation_version" not in columns
    finally:
        await engine.dispose()


async def _assert_backfilled_and_cleanup(
    *,
    agent_id: UUID,
    principal_id: UUID,
    conversation_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(
                        ChatConversation.automation_agent_id,
                        ChatConversation.automation_version,
                    ).where(ChatConversation.id == conversation_id)
                )
            ).one()
            assert row.automation_agent_id == agent_id
            assert row.automation_version == 0
            await db.execute(
                delete(ChatConversation).where(ChatConversation.id == conversation_id)
            )
            await db.execute(delete(Principal).where(Principal.id == principal_id))
            await db.execute(delete(AgentProfile).where(AgentProfile.id == agent_id))
            await db.commit()
    finally:
        await engine.dispose()
