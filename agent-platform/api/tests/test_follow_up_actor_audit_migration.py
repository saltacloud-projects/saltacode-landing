"""Migration coverage for durable operator attribution in follow-up events."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.database import engine

_REVISION = "f8c2d4e6a901"
_DOWN_REVISION = "f7b1c3d5e890"
_CONSTRAINT_COLUMN = "actor_admin_id"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


async def _actor_admin_delete_rule() -> str:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT rc.delete_rule "
                    "FROM information_schema.referential_constraints AS rc "
                    "JOIN information_schema.key_column_usage AS kcu "
                    "ON kcu.constraint_schema = rc.constraint_schema "
                    "AND kcu.constraint_name = rc.constraint_name "
                    "WHERE kcu.table_name = 'follow_up_task_events' "
                    "AND kcu.column_name = :column_name"
                ),
                {"column_name": _CONSTRAINT_COLUMN},
            )
        ).scalar_one()


def test_follow_up_actor_audit_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == ["f13d7b9e1f45"]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_follow_up_actor_audit_migration_changes_delete_rule_and_round_trips() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        assert asyncio.run(_actor_admin_delete_rule()) == "SET NULL"
        asyncio.run(engine.dispose())

        command.upgrade(config, _REVISION)
        assert asyncio.run(_actor_admin_delete_rule()) == "RESTRICT"
        asyncio.run(engine.dispose())

        command.downgrade(config, _DOWN_REVISION)
        assert asyncio.run(_actor_admin_delete_rule()) == "SET NULL"
    finally:
        asyncio.run(engine.dispose())
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())
