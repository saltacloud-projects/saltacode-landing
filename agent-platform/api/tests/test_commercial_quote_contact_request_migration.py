"""Migration coverage for the native quote contact-request capability."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_resource_binding import AgentToolBinding
from app.models.tool_config import ToolConfig

_REVISION = "e1f5a7b9c234"
_DOWN_REVISION = "d0e4f6a8b123"
_HEAD_REVISION = "f11b5f7c9d23"
_TOOL_ID = uuid.UUID("2a0a5cc2-bf7f-4f73-a2eb-11dc7e22b075")
_TOOL_NAME = "commercial_quote_contact_request"


def _config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    return Config(str(api_root / "alembic-platform.ini"))


def test_quote_contact_request_migration_is_the_single_head() -> None:
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_heads() == [_HEAD_REVISION]
    assert scripts.get_revision(_REVISION).down_revision == _DOWN_REVISION


@pytest.mark.integration
def test_migration_seeds_only_the_native_tool_and_rolls_back_its_exact_row() -> None:
    config = _config()
    asyncio.run(engine.dispose())
    try:
        command.upgrade(config, "head")
        asyncio.run(_assert_seeded_tool())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_assert_seeded_tool_absent())

        command.upgrade(config, "head")
        asyncio.run(_assert_seeded_tool_and_rename())
        command.downgrade(config, _DOWN_REVISION)
        asyncio.run(_assert_renamed_row_survives_and_remove_fixture())
    finally:
        command.upgrade(config, "head")
        command.check(config)
        asyncio.run(engine.dispose())


async def _assert_seeded_tool() -> None:
    try:
        async with AsyncSessionLocal() as db:
            tool = (
                await db.execute(select(ToolConfig).where(ToolConfig.id == _TOOL_ID))
            ).scalar_one()
            bindings = (
                (
                    await db.execute(
                        select(AgentToolBinding).where(
                            AgentToolBinding.tool_id == _TOOL_ID
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert tool.tool_name == _TOOL_NAME
            assert tool.handler_kind == "native"
            assert tool.is_enabled is True
            assert tool.allowed_channels == ["web", "whatsapp"]
            assert tool.risk_level == "idempotent"
            assert tool.requires_confirmation is False
            assert bindings == []
    finally:
        await engine.dispose()


async def _assert_seeded_tool_absent() -> None:
    try:
        async with AsyncSessionLocal() as db:
            tool = (
                await db.execute(select(ToolConfig).where(ToolConfig.id == _TOOL_ID))
            ).scalar_one_or_none()
            assert tool is None
    finally:
        await engine.dispose()


async def _assert_seeded_tool_and_rename() -> None:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ToolConfig)
                .where(ToolConfig.id == _TOOL_ID)
                .values(tool_name="operator_owned_contact_request")
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _assert_renamed_row_survives_and_remove_fixture() -> None:
    try:
        async with AsyncSessionLocal() as db:
            tool_name = (
                await db.execute(
                    select(ToolConfig.tool_name).where(ToolConfig.id == _TOOL_ID)
                )
            ).scalar_one()
            assert tool_name == "operator_owned_contact_request"
            await db.execute(delete(ToolConfig).where(ToolConfig.id == _TOOL_ID))
            await db.commit()
    finally:
        await engine.dispose()
