"""Revision and rollback coverage for commercial contact persistence."""

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


def test_commercial_contact_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == ["f3b7c9d1e456"]
    assert scripts.get_revision("4c91b2f7e6a0").down_revision == "8f813973069e"


@pytest.mark.integration
def test_commercial_contact_migration_downgrades_and_upgrades_cleanly() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, "8f813973069e")
    finally:
        command.upgrade(config, "head")
    command.check(config)
    asyncio.run(engine.dispose())
