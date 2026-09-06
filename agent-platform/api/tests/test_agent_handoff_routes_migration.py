"""Revision and rollback coverage for deterministic handoff routes."""

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


def test_agent_handoff_route_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == ["f9d3e5a7b012"]
    assert scripts.get_revision("d0e4f6a8b123").down_revision == "c9d3e5f7a012"


@pytest.mark.integration
def test_agent_handoff_route_migration_downgrades_and_upgrades_cleanly() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, "c9d3e5f7a012")
    finally:
        command.upgrade(config, "head")
    command.check(config)
    asyncio.run(engine.dispose())
