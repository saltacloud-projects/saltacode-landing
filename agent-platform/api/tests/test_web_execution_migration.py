"""Revision and rollback coverage for resumable web execution persistence."""

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


def test_resumable_web_execution_migration_is_the_single_head():
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == ["c9d3e5f7a012"]
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
