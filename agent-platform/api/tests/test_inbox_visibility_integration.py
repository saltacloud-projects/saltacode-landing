"""PostgreSQL proofs for exact operator visibility and truthful live activity."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.database import AsyncSessionLocal
from app.dependencies import get_db
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.inbox_read_receipt import InboxReadReceipt
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.routers.admin import inbox_live
from app.routers.admin.auth import require_admin
from app.routers.admin.operator_inbox import router
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.conversation_control import ConversationNotFoundError
from app.services.inbox_live import inbox_live_snapshot
from app.services.inbox_visibility import mark_inbox_messages_read
from app.services.operator_inbox import operator_inbox_service

pytestmark = pytest.mark.integration


@pytest.fixture
async def context():
    async with AsyncSessionLocal() as db:
        suffix = uuid4().hex
        agents = [
            AgentProfile(
                name=f"Inbox {i}",
                slug=f"inbox-{suffix}-{i}",
                prompt_identity="Test",
                prompt_domain="Test",
                prompt_guardrails="Test",
                unauthorized_message="Unavailable",
                error_message="Unavailable",
            )
            for i in range(2)
        ]
        role = AdminRole(
            key=f"inbox-{suffix[:20]}",
            name="Inbox reader",
            permissions=["conversations.read"],
        )
        principal = Principal(display_name="Synthetic visitor")
        db.add_all([*agents, role, principal])
        await db.flush()
        admins = [
            AdminUser(
                name=f"Reader {i}",
                email=f"inbox-{suffix}-{i}@example.invalid",
                hashed_password="not-a-login",
                role=role.key,
            )
            for i in range(2)
        ]
        conversations = [
            ChatConversation(
                agent_id=agent.id,
                automation_agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                route_key=f"route-{suffix}-{i}",
                external_thread_id=suffix,
            )
            for i, agent in enumerate(agents)
        ]
        db.add_all([*admins, *conversations])
        await db.flush()
        grant = AdminAgentGrant(
            admin_user_id=admins[0].id,
            agent_id=agents[0].id,
            permissions=["conversations.read"],
            is_active=True,
        )
        db.add(grant)
        await db.flush()
        try:
            yield SimpleNamespace(
                db=db,
                agents=agents,
                admins=admins,
                conversations=conversations,
                grant=grant,
                role=role,
            )
        finally:
            await db.rollback()


async def message(db, conversation, role="user", **values):
    result = ChatMessage(
        conversation_id=conversation.id,
        role=role,
        content="Synthetic text",
        client_message_id=uuid4().hex,
        **values,
    )
    db.add(result)
    await db.flush()
    return result


async def thread(context):
    return await operator_inbox_service.get_thread(
        context.db,
        agent_id=context.agents[0].id,
        conversation_id=context.conversations[0].id,
        admin_user_id=context.admins[0].id,
    )


async def snapshot(context):
    agents = await admin_agent_access_service.list_operation_agents(
        context.db,
        admin_user_id=context.admins[0].id,
        role_key=context.admins[0].role,
        permission=AdminPermission.CONVERSATIONS_READ,
    )
    return await inbox_live_snapshot(
        context.db, admin_user_id=context.admins[0].id, agents=agents
    )


@pytest.mark.asyncio
async def test_reads_are_operator_specific_and_only_explicit_displayed_inbound_ids(
    context,
):
    db = context.db
    conversation = context.conversations[0]
    first = await message(db, conversation)
    response = await message(db, conversation, "assistant")
    await message(db, conversation, "system")
    await message(db, conversation, "tool")
    hidden = await message(db, context.conversations[1])
    assert (await thread(context)).conversation.unread_count == 1
    assert (await thread(context)).conversation.unread_count == 1
    assert (
        await db.execute(select(func.count()).select_from(InboxReadReceipt))
    ).scalar_one() == 0
    # A newly visible commit can carry an older transaction timestamp; a watermark would hide it.
    concurrent = await message(
        db, conversation, created_at=datetime.now(UTC) - timedelta(days=1)
    )
    kwargs = dict(
        admin_user_id=context.admins[0].id,
        agent_id=conversation.agent_id,
        conversation_id=conversation.id,
    )
    assert await mark_inbox_messages_read(db, **kwargs, message_ids=[first.id]) == 1
    assert await mark_inbox_messages_read(db, **kwargs, message_ids=[first.id]) == 1
    assert (await thread(context)).conversation.unread_count == 1
    for invalid in (response.id, hidden.id, uuid4()):
        with pytest.raises(ConversationNotFoundError):
            await mark_inbox_messages_read(db, **kwargs, message_ids=[invalid])
    assert (
        await mark_inbox_messages_read(db, **kwargs, message_ids=[concurrent.id]) == 0
    )
    other = await operator_inbox_service.get_thread(
        db,
        agent_id=conversation.agent_id,
        conversation_id=conversation.id,
        admin_user_id=context.admins[1].id,
    )
    assert other.conversation.unread_count == 2


@pytest.mark.asyncio
async def test_active_is_open_not_an_inactivity_or_automation_heuristic(context):
    db = context.db
    conversation = context.conversations[0]
    await message(db, conversation, created_at=datetime.now(UTC) - timedelta(days=30))
    kwargs = dict(agent_id=(conversation.agent_id,), admin_user_id=context.admins[0].id)
    for mode in ("automated", "paused", "human"):
        conversation.control_mode = mode
        conversation.assigned_admin_id = (
            context.admins[0].id if mode == "human" else None
        )
        await db.flush()
        assert (
            await operator_inbox_service.list_conversations(
                db, **kwargs, lifecycle="active"
            )
        ).total == 1
        assert (await snapshot(context)).unread_conversations == 1
    conversation.control_mode = "closed"
    await db.flush()
    assert (
        await operator_inbox_service.list_conversations(
            db, **kwargs, lifecycle="active"
        )
    ).total == 0
    assert (
        await operator_inbox_service.list_conversations(
            db, **kwargs, lifecycle="history"
        )
    ).total == 1
    assert (await snapshot(context)).unread_conversations == 0
    conversation.control_mode = "automated"
    conversation.status = "closed"
    await db.flush()
    assert (
        await operator_inbox_service.list_conversations(
            db, **kwargs, lifecycle="history"
        )
    ).total == 1


@pytest.mark.asyncio
async def test_activity_fences_ownership_control_epochs_and_expired_leases(context):
    db = context.db
    conversation = context.conversations[0]
    inbound = await message(db, conversation)
    execution = ChatExecution(
        request_id=uuid4().hex,
        conversation_id=conversation.id,
        inbound_message_id=inbound.id,
        automation_agent_id=conversation.automation_agent_id,
        control_version=0,
        automation_version=0,
        status="queued",
    )
    db.add(execution)
    await db.flush()
    assert (await thread(context)).conversation.agent_activity.status == "queued"
    execution.status = "running"
    await db.flush()
    assert (await thread(context)).conversation.agent_activity is None
    execution.lease_owner = "synthetic-worker"
    execution.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
    await db.flush()
    assert (await thread(context)).conversation.agent_activity.status == "running"
    before = await snapshot(context)
    execution.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    assert (await thread(context)).conversation.agent_activity is None
    assert (await snapshot(context)).revision != before.revision
    execution.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
    for attribute, wrong in (
        ("control_version", 1),
        ("automation_version", 1),
        ("automation_agent_id", context.agents[1].id),
    ):
        original = getattr(execution, attribute)
        setattr(execution, attribute, wrong)
        await db.flush()
        assert (await thread(context)).conversation.agent_activity is None
        setattr(execution, attribute, original)
    conversation.control_mode = "paused"
    await db.flush()
    assert (await thread(context)).conversation.agent_activity is None
    conversation.control_mode = "automated"
    execution.status = "completed"
    await db.flush()
    assert (await thread(context)).conversation.agent_activity is None


@pytest.mark.asyncio
async def test_live_revision_covers_replies_reads_control_and_effective_grants(context):
    db = context.db
    first = await message(db, context.conversations[0])
    before = await snapshot(context)
    assert before.active_conversations == 1
    assert before.unread_conversations == 1
    await message(db, context.conversations[1])
    assert (await snapshot(context)).revision == before.revision
    await message(db, context.conversations[0], "assistant")
    reply = await snapshot(context)
    assert reply.unread_conversations == 1
    assert reply.revision != before.revision
    context.conversations[0].control_mode = "paused"
    context.conversations[0].control_version += 1
    await db.flush()
    paused = await snapshot(context)
    assert paused.revision != reply.revision
    await mark_inbox_messages_read(
        db,
        admin_user_id=context.admins[0].id,
        agent_id=context.agents[0].id,
        conversation_id=context.conversations[0].id,
        message_ids=[first.id],
    )
    read = await snapshot(context)
    assert read.unread_conversations == 0
    assert read.revision != paused.revision
    context.grant.is_active = False
    await db.flush()
    revoked = await snapshot(context)
    assert revoked.active_conversations == 0
    assert revoked.revision != read.revision
    assert "Synthetic" not in revoked.model_dump_json()


@pytest.mark.asyncio
async def test_live_authentication_rechecks_database_role_user_and_token(
    context, monkeypatch
):
    @asynccontextmanager
    async def session():
        yield context.db

    monkeypatch.setattr(inbox_live, "AsyncSessionLocal", session)
    admin = context.admins[0]
    token = create_access_token(str(admin.id), admin.email, admin.role)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert (
        await inbox_live._authorized_snapshot(credentials)
    ).active_conversations == 1
    context.grant.is_active = False
    await context.db.flush()
    assert (
        await inbox_live._authorized_snapshot(credentials)
    ).active_conversations == 0
    context.role.permissions = []
    await context.db.flush()
    with pytest.raises(HTTPException) as denied:
        await inbox_live._authorized_snapshot(credentials)
    assert denied.value.status_code == 403
    admin.is_active = False
    await context.db.flush()
    with pytest.raises(HTTPException) as denied:
        await inbox_live._authorized_snapshot(credentials)
    assert denied.value.status_code == 401
    with pytest.raises(HTTPException):
        await inbox_live._authorized_snapshot(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid")
        )


@pytest.mark.asyncio
async def test_acknowledgement_route_reauthorizes_and_rejects_foreign_messages(context):
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/agents/{agent_id}/inbox")

    async def database():
        yield context.db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_admin] = lambda: context.admins[0]
    own = await message(context.db, context.conversations[0])
    foreign = await message(context.db, context.conversations[1])
    base = f"/api/admin/agents/{context.agents[0].id}/inbox/{context.conversations[0].id}/read"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(base, json={"message_ids": [str(foreign.id)]})
        ).status_code == 404
        assert (await client.post(base, json={"message_ids": []})).status_code == 422
        assert (
            await client.post(base, json={"message_ids": [str(own.id)]})
        ).json() == {"unread_count": 0}
        context.grant.is_active = False
        await context.db.flush()
        assert (
            await client.post(base, json={"message_ids": [str(own.id)]})
        ).status_code == 403
