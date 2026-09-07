"""Real Redis leases and PostgreSQL scope checks using disposable infrastructure."""

import asyncio
import json
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.dependencies import get_db
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.routers.admin.auth import require_admin
from app.routers.admin.crm import router as crm_router
from app.routers.admin.operator_inbox import router as inbox_router
from app.routers.web_chat_v2 import router as web_router
from app.schemas.chat_presence import TypingSignal
from app.services import chat_presence
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.chat_presence import (
    PresenceRateLimitError,
    PresenceScope,
    publish_presence,
    read_presence,
)
from app.services.inbox_live import inbox_live_snapshot

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_port():
    """Never point lease tests at an existing Redis or shared persistent data."""
    name = f"saltacode-presence-tests-{uuid4().hex[:12]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--publish",
            "127.0.0.1::6379",
            "redis:7.4-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(30):
            result = subprocess.run(
                ["docker", "exec", name, "redis-cli", "ping"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "PONG":
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable presence Redis did not start")
        binding = subprocess.check_output(
            ["docker", "port", name, "6379/tcp"], text=True
        ).strip()
        yield int(binding.rsplit(":", 1)[1])
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


@pytest.fixture
async def redis(redis_port):
    client = Redis(host="127.0.0.1", port=redis_port, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()


def make_scope():
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


def make_signal(instance=None, sequence=0, typing=True):
    return TypingSignal(
        client_instance_id=instance or uuid4(), sequence=sequence, typing=typing
    )


async def publish(redis, scope, signal):
    return await publish_presence(redis, scope=scope, actor="visitor", signal=signal)


@pytest.mark.asyncio
async def test_real_redis_sequences_multitab_cleanup_and_epoch_invalidation(redis):
    scope = make_scope()
    first, second = uuid4(), uuid4()
    active = await publish(redis, scope, make_signal(first, 1))
    assert active.typing
    assert 7 <= (active.expires_at - datetime.now(UTC)).total_seconds() <= 8.1
    await publish(redis, scope, make_signal(second, 1))
    stopped = await publish(redis, scope, make_signal(first, 3, False))
    assert stopped.typing  # Another tab still owns its separate lease.
    await publish(redis, scope, make_signal(first, 2))  # Out-of-order start ignored.
    await publish(redis, scope, make_signal(second, 2, False))
    assert not (await read_presence(redis, [scope]))[
        scope.conversation_id
    ].visitor.typing
    await publish(redis, scope, make_signal(first, 4))
    await publish(redis, scope, make_signal(first, 3, False))  # Late cleanup ignored.
    assert (await read_presence(redis, [scope]))[scope.conversation_id].visitor.typing
    for changes in (
        {"control_version": 4},
        {"automation_version": 3},
        {"automation_agent_id": uuid4()},
        {"agent_id": uuid4()},
        {"conversation_id": uuid4()},
        {"status": "closed"},
    ):
        changed = replace(scope, **changes)
        state = (await read_presence(redis, [changed]))[changed.conversation_id]
        assert not state.visitor.typing
        assert not state.operator.typing
    assert 0 < await redis.pttl(scope.key("visitor")) <= 32_000


@pytest.mark.asyncio
async def test_safe_integer_sequences_survive_redis_json_round_trips(redis):
    scope = make_scope()
    instance = uuid4()
    await publish(redis, scope, make_signal(instance, 9_007_199_254_740_990))
    stopped = await publish(
        redis, scope, make_signal(instance, 9_007_199_254_740_991, False)
    )
    assert not stopped.typing
    duplicate = await publish(
        redis, scope, make_signal(instance, 9_007_199_254_740_990)
    )
    assert not duplicate.typing


@pytest.mark.asyncio
async def test_actor_rate_limit_and_instance_tombstones_bound_memory(redis):
    scope = make_scope()
    for _ in range(6):
        await publish(redis, scope, make_signal())
    with pytest.raises(PresenceRateLimitError):
        await publish(redis, scope, make_signal())
    assert await redis.hlen(scope.key("visitor")) == 6
    await asyncio.sleep(1.05)
    for _ in range(2):
        await publish(redis, scope, make_signal(typing=False))
    with pytest.raises(PresenceRateLimitError):
        await publish(redis, scope, make_signal())
    assert await redis.hlen(scope.key("visitor")) == 8
    assert 0 < await redis.pttl(scope.key("visitor")) <= 32_000
    # Expired tombstones are pruned by the atomic publisher, not accumulated.
    rows = await redis.hgetall(scope.key("visitor"))
    for instance, encoded in rows.items():
        sequence, last_seen, _ = json.loads(encoded)
        await redis.hset(
            scope.key("visitor"),
            instance,
            json.dumps([sequence, last_seen - 33_000, 0]),
        )
    await publish(redis, scope, make_signal())
    assert await redis.hlen(scope.key("visitor")) == 1


@pytest.fixture
async def context(redis):
    async with AsyncSessionLocal() as db:
        suffix = uuid4().hex
        agents = [
            AgentProfile(
                name=f"Presence {i}",
                slug=f"presence-{suffix}-{i}",
                is_public=True,
                is_active=True,
                prompt_identity="Test",
                prompt_domain="Test",
                prompt_guardrails="Test",
                unauthorized_message="Unavailable",
                error_message="Unavailable",
            )
            for i in range(2)
        ]
        role = AdminRole(
            key=f"presence-{suffix[:20]}",
            name="Presence operator",
            permissions=["conversations.read", "conversations.manage"],
        )
        connection = ChannelConnection(
            name="Presence web",
            slug=f"presence-{suffix}",
            channel="web",
        )
        principal = Principal(display_name="Synthetic presence visitor")
        db.add_all([*agents, role, connection, principal])
        await db.flush()
        admins = [
            AdminUser(
                name=f"Synthetic operator {i}",
                email=f"presence-{suffix}-{i}@example.invalid",
                hashed_password="not-a-login",
                role=role.key,
            )
            for i in range(2)
        ]
        routes = [
            ChannelAgentRoute(
                channel="web",
                route_key=f"presence-{suffix}-{i}",
                channel_connection_id=connection.id,
                agent_id=agent.id,
            )
            for i, agent in enumerate(agents)
        ]
        db.add_all([*admins, *routes])
        await db.flush()
        conversations = [
            ChatConversation(
                agent_id=agent.id,
                automation_agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                route_key=route.route_key,
                channel_route_id=route.id,
                external_thread_id=str(uuid4()),
                transcript_consent=True,
                consent_version="test",
                control_mode="human",
                assigned_admin_id=admins[0].id,
            )
            for agent, route in zip(agents, routes, strict=True)
        ]
        grants = [
            AdminAgentGrant(
                admin_user_id=admin.id,
                agent_id=agents[0].id,
                permissions=["conversations.read", "conversations.manage"],
            )
            for admin in admins
        ]
        db.add_all([*conversations, *grants])
        await db.flush()
        app = FastAPI()
        app.state.redis = redis
        app.include_router(web_router)
        app.include_router(inbox_router, prefix="/api/admin/agents/{agent_id}/inbox")
        app.include_router(crm_router, prefix="/api/admin/crm")

        async def use_db():
            yield db

        app.dependency_overrides[get_db] = use_db
        app.dependency_overrides[require_admin] = lambda: admins[0]
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield SimpleNamespace(
                    db=db,
                    redis=redis,
                    app=app,
                    client=client,
                    agents=agents,
                    admins=admins,
                    conversations=conversations,
                    grants=grants,
                    role=role,
                )
        finally:
            await db.rollback()


def private_body(conversation, **changes):
    return {
        **make_signal().model_dump(mode="json"),
        "session_id": conversation.external_thread_id,
        "route_key": conversation.route_key,
        **changes,
    }


def operator_path(context, conversation=None):
    target = conversation or context.conversations[0]
    return f"/api/admin/agents/{target.agent_id}/inbox/{target.id}"


def operator_body(conversation, **changes):
    return {
        **make_signal().model_dump(mode="json"),
        "expected_control_version": conversation.control_version,
        **changes,
    }


async def snapshot(context):
    agents = await admin_agent_access_service.list_operation_agents(
        context.db,
        admin_user_id=context.admins[0].id,
        role_key=context.role.key,
        permission=AdminPermission.CONVERSATIONS_READ,
    )
    return await inbox_live_snapshot(
        context.db,
        admin_user_id=context.admins[0].id,
        agents=agents,
        redis=context.redis,
    )


async def durable_counts(db):
    return [
        await db.scalar(select(func.count()).select_from(model))
        for model in (ChatConversation, ChatMessage, ChatExecution, ConversationEvent)
    ]


@pytest.mark.asyncio
async def test_private_signal_binds_existing_route_and_never_creates_history(context):
    c = context.conversations[0]
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}
    before = await durable_counts(context.db)
    body = private_body(c)
    missing = await context.client.post(
        "/internal/v2/web/presence",
        json={**body, "session_id": str(uuid4())},
        headers=headers,
    )
    assert missing.status_code == 404
    wrong_route = await context.client.post(
        "/internal/v2/web/presence",
        json={**body, "route_key": context.conversations[1].route_key},
        headers=headers,
    )
    assert wrong_route.status_code == 404
    wrong_binding = c.channel_route_id
    c.channel_route_id = context.conversations[1].channel_route_id
    await context.db.flush()
    assert (
        await context.client.post(
            "/internal/v2/web/presence", json=body, headers=headers
        )
    ).status_code == 404
    c.channel_route_id = wrong_binding
    await context.db.flush()
    response = await context.client.post(
        "/internal/v2/web/presence", json=body, headers=headers
    )
    assert response.status_code == 200 and response.json()["typing"] is True
    for endpoint in ("history", "events"):
        response = await context.client.get(
            f"/internal/v2/web/{endpoint}",
            params={"session_id": c.external_thread_id, "route_key": c.route_key},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["presence"] == {
            "operator": {"typing": False, "expires_at": None}
        }
        assert response.json()["activity"] is None
    c.status = "closed"
    await context.db.flush()
    assert (
        await context.client.post(
            "/internal/v2/web/presence", json={**body, "sequence": 1}, headers=headers
        )
    ).status_code == 423
    assert await durable_counts(context.db) == before


@pytest.mark.asyncio
async def test_operator_scope_owner_epochs_public_projection_and_grant_recheck(context):
    c = context.conversations[0]
    body = operator_body(c)
    before = await durable_counts(context.db)
    response = await context.client.post(
        operator_path(context) + "/presence", json=body
    )
    assert response.status_code == 200 and response.json()["typing"]
    for endpoint in ("history", "events"):
        public = await context.client.get(
            f"/internal/v2/web/{endpoint}",
            params={"session_id": c.external_thread_id, "route_key": c.route_key},
            headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
        )
        state = public.json()["presence"]
        assert set(state) == {"operator"}
        assert set(state["operator"]) == {"typing", "expires_at"}
        assert state["operator"]["typing"]
        assert str(context.admins[0].id) not in json.dumps(state)
    thread = await context.client.get(operator_path(context))
    assert thread.json()["conversation"]["presence"]["operator"]["typing"]
    foreign = await context.client.post(
        operator_path(context, context.conversations[1]) + "/presence", json=body
    )
    assert foreign.status_code == 403
    context.app.dependency_overrides[require_admin] = lambda: context.admins[1]
    assert (
        await context.client.post(operator_path(context) + "/presence", json=body)
    ).status_code == 409
    context.app.dependency_overrides[require_admin] = lambda: context.admins[0]
    c.control_version += 1
    await context.db.flush()
    assert (
        await context.client.post(operator_path(context) + "/presence", json=body)
    ).status_code == 409
    assert not (await context.client.get(operator_path(context))).json()[
        "conversation"
    ]["presence"]["operator"]["typing"]
    c.control_mode = "automated"
    await context.db.flush()
    assert (
        await context.client.post(
            operator_path(context) + "/presence", json=operator_body(c)
        )
    ).status_code == 409
    c.control_mode = "human"
    context.grants[0].permissions = ["conversations.read"]
    await context.db.flush()
    assert (
        await context.client.post(
            operator_path(context) + "/presence", json=operator_body(c)
        )
    ).status_code == 403
    assert await durable_counts(context.db) == before


@pytest.mark.asyncio
async def test_presence_invalidates_crm_poll_and_expires_without_any_database_write(
    context,
):
    c = context.conversations[0]
    before = await snapshot(context)
    counts = await durable_counts(context.db)
    clocks = (c.updated_at, c.next_event_sequence, c.control_version)
    # Activity on an unauthorized agent must not invalidate or appear in this Inbox.
    await publish(
        context.redis, PresenceScope.from_model(context.conversations[1]), make_signal()
    )
    assert (await snapshot(context)).revision == before.revision
    await publish(context.redis, PresenceScope.from_model(c), make_signal())
    after = await snapshot(context)
    assert after.revision != before.revision
    assert after.unread_conversations == before.unread_conversations
    response = await context.client.get("/api/admin/crm/inbox")
    assert response.json()["items"][0]["presence"]["visitor"]["typing"]
    await asyncio.sleep(8.05)
    expired = await snapshot(context)
    assert expired.revision == before.revision
    assert not (await context.client.get(operator_path(context))).json()[
        "conversation"
    ]["presence"]["visitor"]["typing"]
    assert await durable_counts(context.db) == counts
    assert clocks == (c.updated_at, c.next_event_sequence, c.control_version)


@pytest.mark.asyncio
async def test_redis_failure_hides_all_read_projections_without_breaking_chat(context):
    c = context.conversations[0]
    await publish(context.redis, PresenceScope.from_model(c), make_signal())
    active = await snapshot(context)
    # Wrong Redis type exercises actual Redis ResponseError rather than mocking projections.
    await context.redis.set(chat_presence._index_key(c.agent_id), "unavailable-index")
    assert (await snapshot(context)).revision != active.revision
    await context.redis.set(
        PresenceScope.from_model(c).key("visitor"), "unavailable-lease"
    )
    thread = await context.client.get(operator_path(context))
    assert thread.status_code == 200
    assert not thread.json()["conversation"]["presence"]["visitor"]["typing"]
    public = await context.client.get(
        "/internal/v2/web/history",
        params={"session_id": c.external_thread_id, "route_key": c.route_key},
        headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
    )
    assert public.status_code == 200
    assert public.json()["presence"] == {
        "operator": {"typing": False, "expires_at": None}
    }


@pytest.mark.asyncio
async def test_agent_indexes_apply_one_aggregate_cap_and_isolate_foreign_activity(
    context,
):
    c = context.conversations[0]
    scope = PresenceScope.from_model(c)
    await publish(context.redis, scope, make_signal())
    visible_index = chat_presence._index_key(c.agent_id)
    foreign_index = chat_presence._index_key(context.agents[1].id)
    seconds, microseconds = await context.redis.time()
    expiry = int(seconds) * 1000 + int(microseconds) // 1000 + 8_000
    fillers = {str(uuid4()): expiry for _ in range(511)}
    await context.redis.zadd(visible_index, fillers)
    await context.redis.zadd(
        foreign_index, {str(uuid4()): expiry for _ in range(1_000)}
    )
    before = await durable_counts(context.db)
    revision = await chat_presence.presence_revision(
        context.db, context.redis, (c.agent_id,)
    )
    assert (
        not revision.degraded
    )  # Exactly 512 authorized candidates; foreign index unread.
    assert len(revision.metadata) == 1
    healthy = await snapshot(context)
    assert not healthy.presence_degraded
    extra = str(uuid4())
    await context.redis.zadd(visible_index, {extra: expiry})
    degraded = await snapshot(context)
    assert degraded.presence_degraded
    assert degraded.revision != healthy.revision
    assert (await snapshot(context)).revision == degraded.revision
    assert degraded.unread_conversations == healthy.unread_conversations
    assert degraded.active_conversations == healthy.active_conversations
    # A selected thread remains safely bounded; consumers hide it using the global flag.
    thread = await context.client.get(operator_path(context))
    assert thread.status_code == 200
    await context.redis.zrem(visible_index, extra)
    recovered = await snapshot(context)
    assert not recovered.presence_degraded
    assert recovered.revision == healthy.revision
    assert await durable_counts(context.db) == before
    # The cap is aggregate, not 512 for each authorized agent/index.
    await context.redis.delete(foreign_index)
    await context.redis.zadd(foreign_index, {str(uuid4()): expiry})
    combined = await chat_presence.presence_revision(
        context.db, context.redis, (c.agent_id, context.agents[1].id)
    )
    assert combined.degraded
    assert combined.metadata == ["capacity"]


@pytest.mark.asyncio
async def test_index_candidates_are_deduplicated_and_overflow_never_reaches_sql(redis):
    first, second = uuid4(), uuid4()
    identifier = uuid4()
    seconds, _ = await redis.time()
    expiry = int(seconds) * 1000 + 8_000
    for agent_id in (first, second):
        await redis.zadd(chat_presence._index_key(agent_id), {str(identifier): expiry})
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    )
    assert not (
        await chat_presence.presence_revision(db, redis, (first, second))
    ).degraded
    statement = db.scalars.call_args.args[0].compile()
    assert statement.params["id_1"] == [identifier]
    db.scalars.reset_mock()
    await redis.zadd(
        chat_presence._index_key(first), {str(uuid4()): expiry for _ in range(513)}
    )
    revision = await chat_presence.presence_revision(db, redis, (first, second))
    assert revision.degraded
    db.scalars.assert_not_called()
