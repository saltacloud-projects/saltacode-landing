"""PostgreSQL migration coverage for durable commercial follow-ups."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
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
from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity
from app.models.platform import Principal

_REVISION = "f5d9e1f3a678"
_HEAD_REVISION = "f6a0b2c4d789"
_DOWN_REVISION = "f4c8d0e2f567"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_durable_follow_up_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_quarantines_legacy_work_and_guards_new_policy_evidence() -> None:
    config = _config()
    ids = {
        key: uuid4()
        for key in (
            "agent",
            "principal",
            "contact",
            "point",
            "consent",
            "opportunity",
            "scheduled_task",
            "completed_task",
        )
    }
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(_create_graph(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_insert_legacy_tasks(ids))
        asyncio.run(engine.dispose())

        command.upgrade(config, "head")
        asyncio.run(_assert_quarantine(ids))
        asyncio.run(engine.dispose())
        asyncio.run(_enable_policy(ids))
        asyncio.run(engine.dispose())
        with pytest.raises(DBAPIError, match="durable follow-up evidence"):
            command.downgrade(config, _DOWN_REVISION)

        asyncio.run(_disable_policy(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_assert_legacy_status_restored(ids))
        asyncio.run(engine.dispose())
    finally:
        command.upgrade(config, "head")
        asyncio.run(_cleanup(ids))
        asyncio.run(engine.dispose())


async def _create_graph(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Follow-up migration agent",
            slug=f"follow-up-migration-{uuid4().hex}",
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
        principal = Principal(id=ids["principal"], display_name="Legacy follow-up")
        db.add_all([agent, principal])
        await db.flush()
        contact = Contact(
            id=ids["contact"],
            principal_id=principal.id,
            created_by_agent_id=agent.id,
            status="active",
        )
        db.add(contact)
        await db.flush()
        point = ContactPoint(
            id=ids["point"],
            contact_id=contact.id,
            kind="email",
            ciphertext="gAAAAA" + ("x" * 80),
            lookup_hmac="e" * 64,
            masked_value="l***@example.com",
            verification_status="unverified",
        )
        db.add(point)
        await db.flush()
        consent = ConsentRecord(
            id=ids["consent"],
            principal_id=principal.id,
            contact_id=contact.id,
            contact_point_id=point.id,
            agent_id=agent.id,
            purpose="commercial_follow_up",
            action="grant",
            policy_version="legacy-v1",
            channel="web",
            locale="es-AR",
            correlation_id="legacy-follow-up-consent",
            idempotency_key="legacy-follow-up-consent",
            command_hash="e" * 64,
            occurred_at=datetime.now(UTC),
        )
        opportunity = Opportunity(
            id=ids["opportunity"],
            contact_id=contact.id,
            created_by_agent_id=agent.id,
            assigned_agent_id=agent.id,
            stage="qualified",
            control_version=0,
            title="Legacy opportunity",
            correlation_id="legacy-follow-up-opportunity",
            idempotency_key="legacy-follow-up-opportunity",
            command_hash="f" * 64,
        )
        db.add_all([consent, opportunity])
        await db.commit()


async def _insert_legacy_tasks(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(UTC)
        statement = text(
            "INSERT INTO follow_up_tasks ("
            "id, opportunity_id, contact_point_id, consent_record_id, "
            "assigned_agent_id, kind, status, state_version, due_at, note, "
            "correlation_id, idempotency_key, command_hash, completed_at"
            ") VALUES ("
            ":id, :opportunity_id, :point_id, :consent_id, :agent_id, "
            "'commercial_follow_up', :status, 0, :due_at, NULL, "
            ":correlation_id, :idempotency_key, :command_hash, :completed_at"
            ")"
        )
        await db.execute(
            statement,
            {
                "id": ids["scheduled_task"],
                "opportunity_id": ids["opportunity"],
                "point_id": ids["point"],
                "consent_id": ids["consent"],
                "agent_id": ids["agent"],
                "status": "scheduled",
                "due_at": now + timedelta(days=1),
                "correlation_id": "legacy-scheduled",
                "idempotency_key": "legacy-scheduled",
                "command_hash": "1" * 64,
                "completed_at": None,
            },
        )
        await db.execute(
            statement,
            {
                "id": ids["completed_task"],
                "opportunity_id": ids["opportunity"],
                "point_id": ids["point"],
                "consent_id": ids["consent"],
                "agent_id": ids["agent"],
                "status": "completed",
                "due_at": now - timedelta(days=1),
                "correlation_id": "legacy-completed",
                "idempotency_key": "legacy-completed",
                "command_hash": "2" * 64,
                "completed_at": now,
            },
        )
        await db.commit()


async def _assert_quarantine(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        scheduled = await db.get(FollowUpTask, ids["scheduled_task"])
        completed = await db.get(FollowUpTask, ids["completed_task"])
        policy = (
            await db.execute(
                select(CommercialAutomationPolicy).where(
                    CommercialAutomationPolicy.agent_id == ids["agent"]
                )
            )
        ).scalar_one()
        event = (
            await db.execute(
                select(FollowUpTaskEvent).where(
                    FollowUpTaskEvent.task_id == ids["scheduled_task"]
                )
            )
        ).scalar_one()
        assert scheduled is not None
        assert scheduled.status == "review_required"
        assert scheduled.last_safe_code == "legacy_follow_up_context_unknown"
        assert scheduled.conversation_id is None
        assert scheduled.target_channel is None
        assert scheduled.scheduled_policy_version is None
        assert completed is not None
        assert completed.status == "completed"
        assert event.event_type == "legacy_quarantined"
        assert event.from_status == "scheduled"
        assert event.to_status == "review_required"
        assert policy.is_enabled is False
        assert policy.allowed_kinds == []
        delete_rule = (
            await db.execute(
                text(
                    "SELECT delete_rule FROM information_schema.referential_constraints "
                    "WHERE constraint_name = 'fk_follow_up_task_conversation'"
                )
            )
        ).scalar_one()
        assert delete_rule == "RESTRICT"


async def _enable_policy(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE commercial_automation_policies SET is_enabled = true "
                "WHERE agent_id = :agent_id"
            ),
            {"agent_id": ids["agent"]},
        )
        await db.commit()


async def _disable_policy(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE commercial_automation_policies SET is_enabled = false "
                "WHERE agent_id = :agent_id"
            ),
            {"agent_id": ids["agent"]},
        )
        await db.commit()


async def _assert_legacy_status_restored(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        rows = dict(
            (
                await db.execute(
                    text(
                        "SELECT id, status FROM follow_up_tasks "
                        "WHERE id IN (:scheduled_id, :completed_id)"
                    ),
                    {
                        "scheduled_id": ids["scheduled_task"],
                        "completed_id": ids["completed_task"],
                    },
                )
            ).all()
        )
        assert rows[ids["scheduled_task"]] == "scheduled"
        assert rows[ids["completed_task"]] == "completed"


async def _cleanup(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FollowUpTaskEvent).where(
                FollowUpTaskEvent.opportunity_id == ids["opportunity"]
            )
        )
        await db.execute(
            delete(FollowUpTask).where(
                FollowUpTask.opportunity_id == ids["opportunity"]
            )
        )
        await db.execute(
            delete(CommercialAutomationPolicy).where(
                CommercialAutomationPolicy.agent_id == ids["agent"]
            )
        )
        await db.execute(
            delete(Opportunity).where(Opportunity.id == ids["opportunity"])
        )
        await db.execute(
            delete(ConsentRecord).where(ConsentRecord.id == ids["consent"])
        )
        await db.execute(delete(ContactPoint).where(ContactPoint.id == ids["point"]))
        await db.execute(delete(Contact).where(Contact.id == ids["contact"]))
        await db.execute(delete(Principal).where(Principal.id == ids["principal"]))
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
