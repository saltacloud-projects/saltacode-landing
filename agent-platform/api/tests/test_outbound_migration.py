"""Revision and rollback coverage for the outbound queue migration."""

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


def test_outbound_migration_is_the_single_head():
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == ["7e702862958d"]
    assert scripts.get_revision("7e702862958d").down_revision == "d7e8f9a0b1c2"


@pytest.mark.integration
def test_outbound_migration_downgrades_and_upgrades_cleanly():
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, "d7e8f9a0b1c2")
    finally:
        command.upgrade(config, "head")
    command.check(config)
    asyncio.run(engine.dispose())
