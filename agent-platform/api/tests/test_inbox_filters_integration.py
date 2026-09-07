"""Database-scoped date/search/unread filtering before count and pagination."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.dependencies import get_db
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.routers.admin.auth import require_admin
from app.routers.admin.crm import router as crm_router
from app.routers.admin.operator_inbox import router as scoped_router
from app.schemas.operator_inbox import InboxMessageFilters
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.inbox_live import inbox_live_snapshot
from app.services.inbox_visibility import mark_inbox_messages_read
from app.services.operator_inbox import operator_inbox_service

pytestmark = pytest.mark.integration
START = datetime(2026, 9, 1, 3, tzinfo=UTC)
END = START + timedelta(days=1)


@pytest.fixture
async def filter_context():
    async with AsyncSessionLocal() as db:
        suffix = uuid4().hex
        agents = [
            AgentProfile(
                name=f"Filter {i}",
                slug=f"filter-{suffix}-{i}",
                prompt_identity="Test",
                prompt_domain="Test",
                prompt_guardrails="Test",
                unauthorized_message="Unavailable",
                error_message="Unavailable",
            )
            for i in range(2)
        ]
        role = AdminRole(
            key=f"filter-{suffix[:20]}",
            name="Filter reader",
            permissions=["conversations.read"],
        )
        db.add_all([*agents, role])
        await db.flush()
        admin = AdminUser(
            name="Filter reader",
            email=f"filter-{suffix}@example.invalid",
            hashed_password="not-a-login",
            role=role.key,
        )
        db.add(admin)
        await db.flush()
        grant = AdminAgentGrant(
            admin_user_id=admin.id,
            agent_id=agents[0].id,
            permissions=["conversations.read"],
            is_active=True,
        )
        db.add(grant)
        rows = {}
        specs = [
            ("empty", "Empty", None),
            ("start", "Alice 100%_ /Team", START),
            ("inside", "Alice second", START + timedelta(hours=4)),
            ("end", "End", END),
            ("before", "Before", START - timedelta(seconds=1)),
            ("anonymous", None, START + timedelta(hours=5)),
            ("hidden", "Hidden name", START + timedelta(hours=6)),
        ]
        for name, display_name, created_at in specs:
            principal = Principal(display_name=display_name)
            db.add(principal)
            await db.flush()
            conversation = ChatConversation(
                agent_id=agents[name == "hidden"].id,
                principal_id=principal.id,
                channel="web",
                route_key=f"filter-{suffix}",
                external_thread_id=f"{suffix}-{name}",
                updated_at=START + timedelta(hours=8),
            )
            db.add(conversation)
            await db.flush()
            message = None
            if created_at:
                message = ChatMessage(
                    conversation_id=conversation.id,
                    client_message_id=uuid4().hex,
                    role="user",
                    content=f"Private transcript {name}",
                    created_at=created_at,
                )
                db.add(message)
                await db.flush()
            rows[name] = SimpleNamespace(
                conversation=conversation, principal=principal, message=message
            )
        app = FastAPI()
        app.include_router(crm_router, prefix="/api/admin/crm")
        app.include_router(scoped_router, prefix="/api/admin/agents/{agent_id}/inbox")

        async def database():
            yield db

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[require_admin] = lambda: admin
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield SimpleNamespace(
                    db=db,
                    agents=agents,
                    admin=admin,
                    role=role,
                    grant=grant,
                    rows=rows,
                    client=client,
                )
        finally:
            await db.rollback()


def paths(context):
    return ["/api/admin/crm/inbox", f"/api/admin/agents/{context.agents[0].id}/inbox/"]


def ids(response):
    return {item["id"] for item in response.json()["items"]}


@pytest.mark.asyncio
async def test_half_open_dates_use_latest_real_message_not_control_activity(
    filter_context,
):
    c = filter_context
    params = {
        "last_message_from": "2026-09-01T00:00:00-03:00",
        "last_message_before": "2026-09-02T00:00:00-03:00",
    }
    expected = {
        str(c.rows[name].conversation.id) for name in ("start", "inside", "anonymous")
    }
    for path in paths(c):
        result = await c.client.get(path, params=params)
        assert result.status_code == 200
        assert result.json()["total"] == 3
        assert ids(result) == expected
        assert str(c.rows["empty"].conversation.id) not in ids(result)
        assert (
            await c.client.get(path, params={**params, "limit": 1, "offset": 2})
        ).json()["total"] == 3
        # An old interval containing an earlier message does not match once a newer reply exists.
    c.db.add(
        ChatMessage(
            conversation_id=c.rows["start"].conversation.id,
            client_message_id=uuid4().hex,
            role="assistant",
            content="New reply",
            created_at=END + timedelta(seconds=1),
        )
    )
    await c.db.flush()
    result = await c.client.get(paths(c)[0], params=params)
    assert result.json()["total"] == 2
    legacy = await c.client.get(
        paths(c)[0], params={"updated_after": START.isoformat()}
    )
    assert str(c.rows["empty"].conversation.id) in ids(legacy)


@pytest.mark.asyncio
async def test_literal_case_insensitive_search_only_matches_visible_label(
    filter_context,
):
    c = filter_context
    for path in paths(c):
        for search in ("ALICE 100%_ /tEaM", "%_", "/Team"):
            result = await c.client.get(path, params={"search": search})
            assert result.status_code == 200
            assert ids(result) == {str(c.rows["start"].conversation.id)}
        result = await c.client.get(
            path, params={"search": "  ALICE  ", "limit": 1, "offset": 1}
        )
        assert result.json()["total"] == 2
        assert len(result.json()["items"]) == 1
        prefix = str(c.rows["anonymous"].principal.id)[:8]
        assert ids(
            await c.client.get(path, params={"search": f"visitante {prefix}"})
        ) == {str(c.rows["anonymous"].conversation.id)}
        assert (
            await c.client.get(path, params={"search": "Private transcript"})
        ).json()["total"] == 0
        assert (await c.client.get(path, params={"search": "Hidden name"})).json()[
            "total"
        ] == 0


@pytest.mark.asyncio
async def test_unread_and_auth_scope_filter_before_pagination_without_changing_global_badge(
    filter_context,
):
    c = filter_context
    options = dict(
        agent_id=c.agents[0].id,
        admin_user_id=c.admin.id,
        conversation_id=c.rows["inside"].conversation.id,
    )
    await mark_inbox_messages_read(
        c.db, **options, message_ids=[c.rows["inside"].message.id]
    )
    accessible = await admin_agent_access_service.list_operation_agents(
        c.db,
        admin_user_id=c.admin.id,
        role_key=c.admin.role,
        permission=AdminPermission.CONVERSATIONS_READ,
    )
    snapshot = await inbox_live_snapshot(
        c.db, admin_user_id=c.admin.id, agents=accessible
    )
    for path in paths(c):
        result = await c.client.get(
            path, params={"search": "Alice", "unread_only": True, "limit": 1}
        )
        assert result.status_code == 200
        assert result.json()["total"] == 1
        assert ids(result) == {str(c.rows["start"].conversation.id)}
        last = await c.client.get(
            path, params={"unread_only": True, "limit": 1, "offset": 3}
        )
        assert last.json()["total"] == 4
        assert len(last.json()["items"]) == 1
    assert (
        await inbox_live_snapshot(c.db, admin_user_id=c.admin.id, agents=accessible)
    ).model_dump() == snapshot.model_dump()
    denied_path = f"/api/admin/agents/{c.agents[1].id}/inbox/"
    assert (
        await c.client.get(denied_path, params={"unread_only": True})
    ).status_code == 403
    assert (
        await c.client.get(
            paths(c)[0], params={"agent_id": str(c.agents[1].id), "search": "Hidden"}
        )
    ).status_code == 403
    c.grant.is_active = False
    await c.db.flush()
    assert (await c.client.get(paths(c)[0], params={"unread_only": True})).json()[
        "total"
    ] == 0
    assert (
        await c.client.get(paths(c)[1], params={"unread_only": True})
    ).status_code == 403
    unscoped = await operator_inbox_service.list_conversations(
        c.db,
        agent_id=(c.agents[0].id,),
        message_filters=InboxMessageFilters(unread_only=True),
    )
    assert unscoped.total == 0


@pytest.mark.asyncio
async def test_preview_is_bounded_deterministic_and_authorship_uses_historical_proof(
    filter_context,
):
    c = filter_context
    target = c.rows["empty"].conversation
    first = ChatMessage(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        conversation_id=target.id,
        client_message_id=uuid4().hex,
        role="user",
        content="Earlier tie",
        created_at=END,
    )
    last = ChatMessage(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        conversation_id=target.id,
        client_message_id=uuid4().hex,
        role="assistant",
        content="  Hello\n\tthere   " + "x" * 180,
        created_at=END,
    )
    c.db.add_all([first, last])
    await c.db.flush()
    result = await c.client.get(paths(c)[0], params={"search": "Empty"})
    item = result.json()["items"][0]
    assert len(item["last_message_preview"]) == 140
    assert item["last_message_preview"].startswith("Hello there ")
    assert item["last_message_at"] == END.isoformat().replace("+00:00", "Z")
    assert item["last_message_author_type"] == "unknown"
    execution = ChatExecution(
        request_id=uuid4().hex,
        conversation_id=target.id,
        inbound_message_id=first.id,
        output_message_id=last.id,
        automation_agent_id=target.agent_id,
        status="completed",
    )
    c.db.add(execution)
    await c.db.flush()
    result = await c.client.get(paths(c)[0], params={"search": "Empty"})
    assert result.json()["items"][0]["last_message_author_type"] == "agent"
    thread_path = f"/api/admin/agents/{target.agent_id}/inbox/{target.id}"
    detail = await c.client.get(thread_path)
    assert [item["author_type"] for item in detail.json()["messages"]] == [
        "visitor",
        "agent",
    ]
    last.metadata_json = {"origin": "operator", "actor_admin_id": str(c.admin.id)}
    target.control_mode = "automated"
    await c.db.flush()
    assert (await c.client.get(thread_path)).json()["messages"][-1][
        "author_type"
    ] == "operator"
    # Exposing a preview remains an authorized conversation read, not a cross-agent search.
    c.grant.is_active = False
    await c.db.flush()
    assert (await c.client.get(thread_path)).status_code == 403


@pytest.mark.asyncio
async def test_empty_preview_is_null_and_system_messages_are_explicit(filter_context):
    c = filter_context
    result = await c.client.get(paths(c)[0], params={"search": "Empty"})
    item = result.json()["items"][0]
    assert item["last_message_at"] is None
    assert item["last_message_preview"] is None
    assert item["last_message_author_type"] is None
    c.db.add(
        ChatMessage(
            conversation_id=c.rows["empty"].conversation.id,
            client_message_id=uuid4().hex,
            role="system",
            content="Workflow updated",
            created_at=END,
        )
    )
    await c.db.flush()
    result = await c.client.get(paths(c)[0], params={"search": "Empty"})
    assert result.json()["items"][0]["last_message_author_type"] == "system"
