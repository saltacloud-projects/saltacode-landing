from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.tools import ToolExecutionContext
from app.services.tool_policy import ToolPolicyService


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return _Rows(self._rows)


class _AgentDb:
    def __init__(self, rows_by_agent):
        self._rows_by_agent = rows_by_agent

    async def execute(self, statement):
        params = set(statement.compile().params.values())
        for agent_id, rows in self._rows_by_agent.items():
            if agent_id in params:
                return _Rows(rows)
        return _Rows([])


def _source(*, public: bool = True, active: bool = True):
    return SimpleNamespace(
        id=uuid4(), slug="catalog", is_public=public, is_active=active
    )


def _tool(
    name: str,
    *,
    channels: list[str] | None = None,
    risk: str = "read_only",
    kind: str = "http_api",
):
    return SimpleNamespace(
        tool_name=name,
        description=name,
        source_system="internal",
        source_id=uuid4(),
        allowed_channels=channels or ["web"],
        risk_level=risk,
        handler_kind=kind,
    )


@pytest.mark.asyncio
async def test_web_tools_require_public_active_source_and_channel() -> None:
    public = _source()
    private = _source(public=False)
    disabled = _source(active=False)
    rows = [
        (_tool("allowed"), public),
        (_tool("private"), private),
        (_tool("disabled"), disabled),
        (_tool("wrong_channel", channels=["api"]), public),
    ]
    context = ToolExecutionContext(request_id="request", channel="web")

    available = await ToolPolicyService().available_tools(
        _Db(rows), context, {"allowed", "private", "disabled", "wrong_channel"}
    )

    assert [item["tool_name"] for item in available] == ["allowed"]
    assert available[0]["source_id"] == str(public.id)


@pytest.mark.asyncio
async def test_source_scope_and_write_scope_are_server_enforced() -> None:
    permitted = _source()
    other = _source()
    rows = [
        (_tool("write_permitted", risk="write"), permitted),
        (_tool("write_other", risk="write"), other),
    ]
    context = ToolExecutionContext(
        request_id="request",
        channel="web",
        scopes={"tools:write"},
        allowed_source_ids={str(permitted.id)},
    )

    available = await ToolPolicyService().available_tools(
        _Db(rows), context, {"write_permitted", "write_other"}
    )

    assert [item["tool_name"] for item in available] == ["write_permitted"]

    context.scopes.clear()
    assert (
        await ToolPolicyService().available_tools(
            _Db(rows), context, {"write_permitted", "write_other"}
        )
        == []
    )


@pytest.mark.asyncio
async def test_agent_binding_isolation_filters_tools_and_sources() -> None:
    agent_a = uuid4()
    agent_b = uuid4()
    source_a = _source()
    source_b = _source()
    tool_a = _tool("agent_a_tool")
    tool_b = _tool("agent_b_tool")
    db = _AgentDb({agent_a: [(tool_a, source_a)], agent_b: [(tool_b, source_b)]})
    runtime_tools = {"agent_a_tool", "agent_b_tool"}

    available_a = await ToolPolicyService().available_tools(
        db,
        ToolExecutionContext(
            request_id="request-a", channel="web", agent_id=str(agent_a)
        ),
        runtime_tools,
    )
    available_b = await ToolPolicyService().available_tools(
        db,
        ToolExecutionContext(
            request_id="request-b", channel="web", agent_id=str(agent_b)
        ),
        runtime_tools,
    )

    assert [item["tool_name"] for item in available_a] == ["agent_a_tool"]
    assert [item["tool_name"] for item in available_b] == ["agent_b_tool"]
