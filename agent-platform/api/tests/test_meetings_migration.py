"""PostgreSQL migration coverage for the auditable meeting aggregate."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.contact import Contact
from app.models.meeting import Meeting, MeetingEvent
from app.models.opportunity import Opportunity
from app.models.platform import Principal

_REVISION = "f10a4e6b8c12"
_HEAD_REVISION = "f11b5f7c9d23"
_DOWN_REVISION = "f9d3e5a7b012"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_meeting_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_meeting_migration_round_trips_empty_and_blocks_evidence_loss() -> None:
    config = _config()
    ids = {
        key: uuid4()
        for key in ("agent", "admin", "principal", "contact", "opportunity", "meeting")
    }
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, _REVISION)
        asyncio.run(engine.dispose())
        asyncio.run(_insert_meeting_evidence(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(DBAPIError, match="meeting evidence must be preserved"):
            command.downgrade(config, _DOWN_REVISION)
        asyncio.run(engine.dispose())
        asyncio.run(_delete_meeting_evidence(ids))
        asyncio.run(engine.dispose())

        command.downgrade(config, _DOWN_REVISION)
    finally:
        asyncio.run(engine.dispose())
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())
        asyncio.run(_delete_meeting_evidence(ids))
        asyncio.run(engine.dispose())


async def _insert_meeting_evidence(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Meeting migration agent",
            slug=f"meeting-migration-{uuid4().hex}",
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
        admin = AdminUser(
            id=ids["admin"],
            email=f"meeting-migration-{uuid4().hex}@example.test",
            hashed_password="not-used",
            name="Meeting migration operator",
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        principal = Principal(id=ids["principal"])
        db.add_all([agent, admin, principal])
        await db.flush()
        contact = Contact(
            id=ids["contact"],
            principal_id=principal.id,
            created_by_agent_id=agent.id,
            status="active",
        )
        db.add(contact)
        await db.flush()
        opportunity = Opportunity(
            id=ids["opportunity"],
            contact_id=contact.id,
            created_by_agent_id=agent.id,
            assigned_agent_id=agent.id,
            assigned_operator_id=admin.id,
            stage="new",
            control_version=0,
            title="Migration meeting",
            correlation_id="meeting-migration",
            idempotency_key="meeting-migration",
            command_hash="a" * 64,
        )
        db.add(opportunity)
        await db.flush()
        meeting = Meeting(
            id=ids["meeting"],
            opportunity_id=opportunity.id,
            conversation_id=None,
            created_under_agent_id=agent.id,
            created_by_agent_id=None,
            created_by_admin_id=admin.id,
            status="requested",
            state_version=0,
            proposal_version=0,
            correlation_id="meeting-migration",
            idempotency_key="meeting-migration",
            command_hash="b" * 64,
        )
        db.add(meeting)
        await db.flush()
        db.add(
            MeetingEvent(
                meeting_id=meeting.id,
                opportunity_id=opportunity.id,
                conversation_id=None,
                actor_type="operator",
                actor_agent_id=None,
                actor_admin_id=admin.id,
                assigned_agent_id=agent.id,
                assigned_operator_id=admin.id,
                routing_agent_id=None,
                automation_agent_id=None,
                event_type="created",
                from_status=None,
                to_status="requested",
                state_version=0,
                proposal_version=0,
                opportunity_control_version=0,
                slot_id=None,
                conversation_control_version=None,
                conversation_automation_version=None,
                source_channel=None,
                correlation_id="meeting-migration",
                idempotency_key="meeting-migration",
                command_hash="c" * 64,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()


async def _delete_meeting_evidence(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(MeetingEvent).where(MeetingEvent.meeting_id == ids["meeting"])
        )
        await db.execute(delete(Meeting).where(Meeting.id == ids["meeting"]))
        await db.execute(
            delete(Opportunity).where(Opportunity.id == ids["opportunity"])
        )
        await db.execute(delete(Contact).where(Contact.id == ids["contact"]))
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(delete(AdminUser).where(AdminUser.id == ids["admin"]))
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
