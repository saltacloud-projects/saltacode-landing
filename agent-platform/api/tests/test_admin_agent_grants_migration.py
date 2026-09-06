"""Revision and rollback coverage for administrator-to-agent grants."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.database import engine


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_admin_agent_grant_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == ["f8c2d4e6a901"]
    assert scripts.get_revision("b8c2d4e6f901").down_revision == "a6f1d2c3e4b5"


@pytest.mark.integration
def test_admin_agent_grant_migration_downgrades_and_upgrades_cleanly() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, "a6f1d2c3e4b5")
    finally:
        command.upgrade(config, "head")
    command.check(config)
    asyncio.run(engine.dispose())
