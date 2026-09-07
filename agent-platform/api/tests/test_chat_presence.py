"""Content-free typing contracts and optional failure behavior without infrastructure."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.config import settings
from app.dependencies import get_db
from app.routers.admin.operator_inbox import router as admin_router
from app.routers.web_chat_v2 import router as web_router
from app.schemas.chat_presence import OperatorTypingSignal, TypingSignal, TypingState
from app.schemas.web_chat_v2 import WebEventsResponse, WebTypingSignal
from app.services import chat_presence
from app.services.chat_presence import (
    PresenceClosedError,
    PresenceConflictError,
    PresenceRateLimitError,
    PresenceScope,
    publish_presence,
    read_presence,
)
from app.services.web_chat_v2 import WebChatV2Service


def scope():
    return PresenceScope(
        conversation_id=uuid4(),
        agent_id=uuid4(),
        channel="web",
        control_mode="human",
        control_version=3,
        automation_version=2,
        automation_agent_id=uuid4(),
        status="active",
        assigned_admin_id=uuid4(),
    )


def signal(**values):
    return TypingSignal(
        **{"client_instance_id": uuid4(), "sequence": 0, "typing": True, **values}
    )


@pytest.mark.parametrize(
    "values",
    [
        {"typing": "true"},
        {"typing": 1},
        {"sequence": True},
        {"sequence": -1},
        {"sequence": 2**53},
        {"sequence": "1"},
        {"sequence": 1.2},
        {"client_instance_id": "not-a-uuid"},
        {"text": "private draft"},
        {"actor_admin_id": str(uuid4())},
    ],
)
def test_typing_signal_rejects_unbounded_or_content_fields(values):
    with pytest.raises(ValidationError):
        signal(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"typing": True},
        {"typing": False, "expires_at": "2026-09-07T12:00:00Z"},
        {"typing": True, "expires_at": "2026-09-07T12:00:00"},
        {"typing": "false"},
    ],
)
def test_presence_state_requires_boolean_and_coherent_aware_expiry(values):
    with pytest.raises(ValidationError):
        TypingState(**values)


def test_old_event_pages_default_to_no_operator_presence():
    response = WebEventsResponse(after=0, next_cursor=0, has_more=False, events=[])
    assert response.presence.model_dump() == {
        "operator": {"typing": False, "expires_at": None}
    }
    with pytest.raises(ValidationError):
        OperatorTypingSignal(**signal().model_dump(), expected_control_version=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["automated", "paused", "human"])
async def test_visitor_can_signal_in_all_open_modes_without_redis(mode):
    state = await publish_presence(
        None,
        scope=replace(scope(), control_mode=mode),
        actor="visitor",
        signal=signal(),
    )
    assert state == TypingState()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"control_mode": "closed"},
        {"status": "closed"},
        {"channel": "whatsapp"},
    ],
)
async def test_closed_or_external_channels_do_not_publish(changes):
    redis = SimpleNamespace(eval=AsyncMock())
    with pytest.raises(PresenceClosedError):
        await publish_presence(
            redis, scope=replace(scope(), **changes), actor="visitor", signal=signal()
        )
    redis.eval.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["owner", "epoch", "automated", "paused"])
async def test_operator_requires_current_human_owner_and_epoch(violation):
    current = scope()
    redis = SimpleNamespace(eval=AsyncMock())
    owner, version = current.assigned_admin_id, current.control_version
    if violation == "owner":
        owner = uuid4()
    elif violation == "epoch":
        version -= 1
    else:
        current = replace(current, control_mode=violation)
    with pytest.raises(PresenceConflictError):
        await publish_presence(
            redis,
            scope=current,
            actor="operator",
            actor_admin_id=owner,
            expected_control_version=version,
            signal=signal(),
        )
    redis.eval.assert_not_called()


@pytest.mark.asyncio
async def test_redis_failures_hide_presence_and_slow_dependency_is_bounded():
    current = scope()
    broken = SimpleNamespace(eval=AsyncMock(side_effect=RedisError("unavailable")))
    assert (
        await publish_presence(broken, scope=current, actor="visitor", signal=signal())
        == TypingState()
    )

    async def stall(*_args):
        await asyncio.sleep(30)

    async with asyncio.timeout(1):
        assert (
            await publish_presence(
                SimpleNamespace(eval=stall),
                scope=current,
                actor="visitor",
                signal=signal(),
            )
            == TypingState()
        )
    states = await read_presence(None, [current])
    assert not states[current.conversation_id].visitor.typing


@pytest.mark.asyncio
async def test_rate_limit_is_not_misreported_as_redis_unavailability():
    with pytest.raises(PresenceRateLimitError):
        await publish_presence(
            SimpleNamespace(eval=AsyncMock(return_value=[0, 1])),
            scope=scope(),
            actor="visitor",
            signal=signal(),
        )


@pytest.mark.asyncio
async def test_private_signal_only_resolves_existing_session(monkeypatch):
    service = WebChatV2Service()
    current = scope()
    conversation = SimpleNamespace(
        id=current.conversation_id,
        agent_id=current.agent_id,
        **{
            key: value
            for key, value in current.__dict__.items()
            if key not in {"conversation_id", "agent_id"}
        },
        transcript_consent=True,
    )
    route = object()
    monkeypatch.setattr(service, "_resolve_route_scope", AsyncMock(return_value=route))
    lookup = AsyncMock(return_value=conversation)
    monkeypatch.setattr(service, "_find_session", lookup)
    create = AsyncMock()
    monkeypatch.setattr(service, "_resolve_session", create)
    request = WebTypingSignal(
        **signal().model_dump(), session_id=uuid4(), route_key="existing-web"
    )
    db = object()
    await service.typing_presence(db, request)
    lookup.assert_awaited_once_with(
        db, scope=route, session_id=request.session_id, for_update=False
    )
    create.assert_not_called()


def test_presence_routes_keep_existing_private_and_admin_bearer_boundaries():
    app = FastAPI()
    app.include_router(web_router)
    app.include_router(admin_router, prefix="/api/admin/agents/{agent_id}/inbox")
    paths = app.openapi()["paths"]
    private = paths["/internal/v2/web/presence"]["post"]
    admin = paths["/api/admin/agents/{agent_id}/inbox/{conversation_id}/presence"][
        "post"
    ]
    assert private["security"] == [{"HTTPBearer": []}]
    assert admin["security"] == [{"HTTPBearer": []}]


@pytest.mark.asyncio
async def test_private_presence_rejects_unauthenticated_and_draft_body():
    app = FastAPI()
    app.include_router(web_router)
    app.dependency_overrides[get_db] = lambda: None
    body = {
        **signal().model_dump(mode="json"),
        "session_id": str(uuid4()),
        "route_key": "existing-web",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/internal/v2/web/presence", json=body)
        ).status_code == 401
        invalid = await client.post(
            "/internal/v2/web/presence",
            json={**body, "draft": "never accepted"},
            headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
        )
        assert invalid.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [64, 65])
async def test_live_presence_bounds_authorized_indexes_before_redis_or_sql(count):
    ids = tuple(uuid4() for _ in range(count))
    db = SimpleNamespace(scalars=AsyncMock())
    redis = SimpleNamespace(eval=AsyncMock(return_value=[]))
    revision = await chat_presence.presence_revision(db, redis, ids)
    assert revision.degraded is (count == 65)
    db.scalars.assert_not_called()
    if count == 65:
        redis.eval.assert_not_called()
        assert revision.metadata == ["capacity"]
    else:
        args = redis.eval.call_args.args
        assert args[1] == 64
        assert args[2:-1] == tuple(
            chat_presence._index_key(identifier) for identifier in ids
        )
        assert args[-1] == 512


@pytest.mark.asyncio
async def test_live_presence_overflow_and_unavailable_are_distinct_without_sql():
    db = SimpleNamespace(scalars=AsyncMock())
    ids = (uuid4(),)
    overflow = await chat_presence.presence_revision(
        db, SimpleNamespace(eval=AsyncMock(return_value=[b"overflow"])), ids
    )
    unavailable = await chat_presence.presence_revision(
        db, SimpleNamespace(eval=AsyncMock(side_effect=RedisError("offline"))), ids
    )
    assert overflow.degraded and unavailable.degraded
    assert overflow.metadata == ["capacity"]
    assert unavailable.metadata == ["unavailable"]
    db.scalars.assert_not_called()


@pytest.mark.asyncio
async def test_presence_pipeline_has_an_independent_aggregate_scope_cap():
    redis = SimpleNamespace(pipeline=AsyncMock())
    scopes = [scope() for _ in range(513)]
    states = await read_presence(redis, scopes)
    assert len(states) == 513
    assert all(
        not state.visitor.typing and not state.operator.typing
        for state in states.values()
    )
    redis.pipeline.assert_not_called()
