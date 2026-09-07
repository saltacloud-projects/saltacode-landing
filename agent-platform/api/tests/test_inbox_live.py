"""SSE wire and lifecycle checks without provider or database side effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException

from app.routers.admin import inbox_live
from app.schemas.operator_inbox import InboxLiveSnapshotOut


def snapshot(revision="one"):
    return InboxLiveSnapshotOut(
        revision=revision,
        unread_conversations=1,
        active_conversations=2,
        historical_conversations=3,
    )


def test_live_stream_uses_bearer_header_without_query_credentials():
    app = FastAPI()
    app.include_router(inbox_live.router, prefix="/api/admin/crm")
    operation = app.openapi()["paths"]["/api/admin/crm/inbox/live"]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "parameters" not in operation


@pytest.mark.asyncio
async def test_stream_emits_changed_snapshot_then_terminates_after_revocation(
    monkeypatch,
):
    monkeypatch.setattr(inbox_live.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        inbox_live,
        "_authorized_snapshot",
        AsyncMock(side_effect=[snapshot("two"), HTTPException(status_code=401)]),
    )
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    stream = inbox_live._stream(request, None, snapshot())
    assert '"revision":"one"' in await anext(stream)
    assert '"revision":"two"' in await anext(stream)
    assert "event: inbox.access_revoked" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_stream_stops_when_browser_disconnects(monkeypatch):
    monkeypatch.setattr(inbox_live.asyncio, "sleep", AsyncMock())
    authorized = AsyncMock()
    monkeypatch.setattr(inbox_live, "_authorized_snapshot", authorized)
    stream = inbox_live._stream(
        SimpleNamespace(is_disconnected=AsyncMock(return_value=True)), None, snapshot()
    )
    await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    authorized.assert_not_called()


@pytest.mark.asyncio
async def test_unchanged_stream_heartbeats_and_rotates_at_bounded_lifetime(monkeypatch):
    clock = iter([0.0, 1.0, 20.0, 20.0, 301.0])
    monkeypatch.setattr(
        inbox_live, "time", SimpleNamespace(monotonic=lambda: next(clock))
    )
    monkeypatch.setattr(inbox_live.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        inbox_live, "_authorized_snapshot", AsyncMock(return_value=snapshot())
    )
    stream = inbox_live._stream(
        SimpleNamespace(is_disconnected=AsyncMock(return_value=False)), None, snapshot()
    )
    await anext(stream)
    assert await anext(stream) == ": heartbeat\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
