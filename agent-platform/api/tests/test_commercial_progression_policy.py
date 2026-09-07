"""Configuration validation and additive migration preservation."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import text

from app.core.database import engine
from app.schemas.commercial_progression import CommercialProgressionUpdate


def _config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic-platform.ini"))


def test_progression_revision_is_the_single_additive_head():
    scripts = ScriptDirectory.from_config(_config())
    assert scripts.get_heads() == ["f15f9d1a3b67"]
    assert scripts.get_revision("f14e8c0f2a56").down_revision == "f13d7b9e1f45"


@pytest.mark.parametrize(
    "payload",
    [
        {"quote_request_action": "run_arbitrary_code", "expected_version": 0},
        {"quote_request_action": "keep_agent", "expected_version": -1},
        {
            "quote_request_action": "keep_agent",
            "expected_version": 0,
            "disable_consent": True,
        },
    ],
)
def test_guided_policy_cannot_override_invariants(payload):
    with pytest.raises(ValidationError):
        CommercialProgressionUpdate.model_validate(payload)


async def _execute(statement, **parameters):
    async with engine.begin() as connection:
        result = await connection.execute(text(statement), parameters)
        value = result.scalar() if result.returns_rows else None
    await engine.dispose()
    return value


@pytest.mark.integration
def test_progression_upgrade_preserves_agents_and_blocks_configured_downgrade():
    config = _config()
    agent_id = uuid4()
    asyncio.run(engine.dispose())
    command.downgrade(config, "f13d7b9e1f45")
    try:
        asyncio.run(
            _execute(
                """INSERT INTO agent_profiles
            (id, name, slug, version, is_active, is_public, retention_days,
             prompt_identity, prompt_domain, prompt_guardrails, unauthorized_message, error_message)
            VALUES (:id, 'Preserved agent', :slug, 1, true, false, 30,
                    'identity', 'domain', 'guardrails', 'denied', 'unavailable')""",
                id=agent_id,
                slug=f"migration-{agent_id}",
            )
        )
        command.upgrade(config, "head")
        assert (
            asyncio.run(
                _execute("SELECT name FROM agent_profiles WHERE id=:id", id=agent_id)
            )
            == "Preserved agent"
        )
        assert (
            asyncio.run(
                _execute("SELECT count(*) FROM commercial_progression_policies")
            )
            == 0
        )
        asyncio.run(
            _execute(
                "INSERT INTO commercial_progression_policies (agent_id, quote_request_action, version) VALUES (:id, 'keep_agent', 1)",
                id=agent_id,
            )
        )
        with pytest.raises(RuntimeError, match="Cannot discard"):
            command.downgrade(config, "f13d7b9e1f45")
        assert (
            asyncio.run(
                _execute(
                    "SELECT quote_request_action FROM commercial_progression_policies WHERE agent_id=:id",
                    id=agent_id,
                )
            )
            == "keep_agent"
        )
        command.check(config)
    finally:
        command.upgrade(config, "head")
        asyncio.run(_execute("DELETE FROM agent_profiles WHERE id=:id", id=agent_id))
