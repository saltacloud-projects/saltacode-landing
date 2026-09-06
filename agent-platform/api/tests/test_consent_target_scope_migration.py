"""Migration coverage for target-scoped commercial consent."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.database import engine

_REVISION = "f6a0b2c4d789"
_DOWN_REVISION = "f5d9e1f3a678"
_HEAD_REVISION = "f7b1c3d5e890"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_target_scoped_consent_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_target_scoped_consent_migration_round_trips_without_evidence() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.downgrade(config, _DOWN_REVISION)
        command.upgrade(config, _REVISION)
        command.upgrade(config, _HEAD_REVISION)
        command.check(config)
    finally:
        command.upgrade(config, "head")
        asyncio.run(engine.dispose())
