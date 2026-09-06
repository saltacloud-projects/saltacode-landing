"""PostgreSQL migration coverage for neutral external-channel ingress."""

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
from app.models.channel_inbound import ChannelInboundEvent, ChannelInboundJob

_REVISION = "f12c6a8d0e34"
_DOWN_REVISION = "f11b5f7c9d23"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_channel_inbound_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_preserves_terminal_and_quarantines_unfinished_legacy_jobs() -> None:
    config = _config()
    ids = {key: uuid4() for key in ("agent", "connection", "route", *_STATUSES)}
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_insert_legacy_graph(ids))
        asyncio.run(engine.dispose())

        command.upgrade(config, _REVISION)
        asyncio.run(_assert_legacy_disposition(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(DBAPIError, match="acceptance snapshot is immutable"):
            asyncio.run(_mutate_acceptance_snapshot(ids))
        asyncio.run(engine.dispose())

        with pytest.raises(RuntimeError, match="channel ingress evidence"):
            command.downgrade(config, _DOWN_REVISION)

        asyncio.run(_delete_jobs(ids))
        asyncio.run(engine.dispose())
        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, _REVISION)
    finally:
        asyncio.run(engine.dispose())
        command.upgrade(config, "head")
        asyncio.run(_cleanup_graph(ids))
        asyncio.run(engine.dispose())


_STATUSES = ("completed", "queued", "processing", "failed")


async def _insert_legacy_graph(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            id=ids["agent"],
            name="Channel inbound migration agent",
            slug=f"channel-inbound-migration-{uuid4().hex}",
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
            name="Channel inbound migration connection",
            slug=f"channel-inbound-migration-{uuid4().hex}",
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            version=0,
            external_account_id=f"migration-{uuid4().hex}",
            settings_json={},
            is_active=True,
        )
        db.add_all([agent, connection])
        await db.flush()
        route = ChannelAgentRoute(
            id=ids["route"],
            channel="whatsapp",
            version=0,
            route_key=f"channel-inbound-migration-{uuid4().hex}",
            channel_connection_id=connection.id,
            agent_id=agent.id,
            is_active=True,
        )
        db.add(route)
        await db.flush()
        statement = text(
            "INSERT INTO whatsapp_inbound_jobs ("
            "id, channel_route_id, channel_connection_id, provider_message_id, "
            "payload_json, status, attempts, max_attempts"
            ") VALUES ("
            ":id, :route_id, :connection_id, :message_id, "
            "CAST(:payload AS jsonb), :status, :attempts, 5"
            ")"
        )
        for status in _STATUSES:
            await db.execute(
                statement,
                {
                    "id": ids[status],
                    "route_id": route.id,
                    "connection_id": connection.id,
                    "message_id": f"migration-{status}",
                    "payload": "{}" if status == "completed" else '{"legacy":true}',
                    "status": status,
                    "attempts": 1 if status in {"processing", "failed"} else 0,
                },
            )
        await db.commit()


async def _assert_legacy_disposition(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        jobs = {
            job.legacy_status: job
            for job in (
                (
                    await db.execute(
                        select(ChannelInboundJob).where(
                            ChannelInboundJob.id.in_(
                                [ids[value] for value in _STATUSES]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        assert set(jobs) == set(_STATUSES)
        assert jobs["completed"].status == "completed"
        assert jobs["completed"].phase == "terminal"
        assert jobs["completed"].legacy_payload_json is None
        for status in ("queued", "processing", "failed"):
            job = jobs[status]
            assert job.status == "review_required"
            assert job.phase == "legacy_quarantined"
            assert job.safe_code == "legacy_payload_quarantined"
            assert job.legacy_payload_json == {"legacy": True}
            assert job.payload_ciphertext is None
            assert job.thread_key is None

        events = list(
            (
                await db.execute(
                    select(ChannelInboundEvent).where(
                        ChannelInboundEvent.job_id.in_(
                            [ids[value] for value in _STATUSES]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == len(_STATUSES)
        assert {event.event_type for event in events} == {
            "legacy_completed_migrated",
            "legacy_quarantined",
        }
        assert {event.state_version for event in events} == {0}


async def _delete_jobs(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        job_ids = [ids[value] for value in _STATUSES]
        await db.execute(
            delete(ChannelInboundEvent).where(ChannelInboundEvent.job_id.in_(job_ids))
        )
        await db.execute(
            delete(ChannelInboundJob).where(ChannelInboundJob.id.in_(job_ids))
        )
        await db.commit()


async def _mutate_acceptance_snapshot(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text(
                    "UPDATE channel_inbound_jobs SET provider_message_id = :value "
                    "WHERE id = :id"
                ),
                {"id": ids["queued"], "value": "mutated-provider-message"},
            )
            await db.commit()
        finally:
            await db.rollback()


async def _cleanup_graph(ids: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id == ids["route"])
        )
        await db.execute(
            delete(ChannelConnection).where(ChannelConnection.id == ids["connection"])
        )
        await db.execute(delete(AgentProfile).where(AgentProfile.id == ids["agent"]))
        await db.commit()
