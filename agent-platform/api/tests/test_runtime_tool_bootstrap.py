"""Worker-local capability composition must not depend on FastAPI lifespan."""

import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.tools import bootstrap, dynamic
from app.services.tools.registry import ToolRegistry
from app.services.web_execution_runner import WebExecutionRunner

NATIVE_TOOLS = {"commercial_quote_contact_request", "rag_documento_enviar"}


def test_fresh_web_worker_registers_native_tools_without_api_lifespan():
    script = """
import asyncio
import sys
from app.services.tools.registry import tool_registry
from app.workers import web_executions
assert 'app.main' not in sys.modules
assert tool_registry.list_tools() == []
class Worker:
    def __init__(self, runner, **kwargs):
        assert set(tool_registry.list_tools()) == {
            'commercial_quote_contact_request', 'rag_documento_enviar'
        }
    async def run_forever(self, stop_event):
        assert 'app.main' not in sys.modules
web_executions.WebExecutionWorker = Worker
asyncio.run(web_executions._run_worker())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def isolated_registry(monkeypatch):
    registry = ToolRegistry()
    monkeypatch.setattr(bootstrap, "tool_registry", registry)
    monkeypatch.setattr(dynamic, "tool_registry", registry)
    monkeypatch.setattr(dynamic, "_http_api_tool_names", set())
    monkeypatch.setattr("app.services.web_execution_runner.tool_registry", registry)
    return registry


@pytest.mark.asyncio
async def test_runtime_sync_refreshes_declarative_tools_without_losing_native_handlers(
    isolated_registry, caplog
):
    configs = [
        SimpleNamespace(
            tool_name="first_api",
            http_config={"private_test_marker": "must-not-be-logged"},
        )
    ]
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: configs)
            )
        )
    )

    assert await bootstrap.sync_runtime_tools(db) == 1
    assert set(isolated_registry.list_tools()) == NATIVE_TOOLS | {"first_api"}
    configs[:] = [SimpleNamespace(tool_name="second_api")]
    assert await bootstrap.sync_runtime_tools(db) == 1
    assert set(isolated_registry.list_tools()) == NATIVE_TOOLS | {"second_api"}
    configs.clear()
    assert await bootstrap.sync_runtime_tools(db) == 0
    assert set(isolated_registry.list_tools()) == NATIVE_TOOLS
    assert "must-not-be-logged" not in caplog.text


@pytest.mark.asyncio
async def test_runner_refreshes_process_registry_before_policy_snapshot(
    isolated_registry, monkeypatch
):
    agent_id, route_id = uuid4(), uuid4()
    conversation = SimpleNamespace(
        id=uuid4(),
        channel_route_id=route_id,
        agent_id=agent_id,
        route_key="test-route",
        principal_id=uuid4(),
        external_thread_id="test-session",
    )
    route = SimpleNamespace(id=route_id, agent_id=agent_id)
    runtime = SimpleNamespace(config=SimpleNamespace(history_message_limit=20))
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(one_or_none=lambda: conversation)
                ),
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(
                        all=lambda: [SimpleNamespace(tool_name="current_api")]
                    )
                ),
            ]
        )
    )

    async def available_tools(_db, context, registered_tools):
        assert registered_tools == NATIVE_TOOLS | {"current_api"}
        assert context.agent_id == str(agent_id)
        return [{"tool_name": "commercial_quote_contact_request"}]

    runner = WebExecutionRunner(
        worker_id="synthetic-worker",
        lease_duration=timedelta(minutes=5),
        runtime_resolver=SimpleNamespace(
            resolve_channel_route=AsyncMock(return_value=SimpleNamespace(route=route)),
            resolve_agent=AsyncMock(return_value=runtime),
        ),
        policy_service=SimpleNamespace(available_tools=available_tools),
    )
    monkeypatch.setattr(runner, "_load_tool_configs", AsyncMock(return_value={}))
    monkeypatch.setattr(runner, "_load_history", AsyncMock(return_value=[]))
    claim = SimpleNamespace(
        execution=SimpleNamespace(
            conversation_id=conversation.id,
            automation_agent_id=agent_id,
            request_id="synthetic-turn",
            control_version=0,
            automation_version=0,
        ),
        inbound_message=SimpleNamespace(id=uuid4()),
    )

    prepared = await runner._prepare(db, claim)

    assert prepared.tools == [{"tool_name": "commercial_quote_contact_request"}]
