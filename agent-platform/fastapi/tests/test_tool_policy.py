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
