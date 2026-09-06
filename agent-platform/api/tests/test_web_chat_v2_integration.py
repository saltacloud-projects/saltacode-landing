"""PostgreSQL integration coverage for the private durable web-chat API."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.routers.web_chat_v2 import router
from app.schemas.conversation_control import ConversationControlMode
from app.services.conversation_control import ConversationControlService
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _WebRouteGraph:
    agent_id: UUID
    admin_id: UUID
    admin_role_key: str
    connection_id: UUID
    route_ids: tuple[UUID, UUID]
    route_keys: tuple[str, str]


@pytest.fixture
async def web_route_graph():
    agent_id = None
    admin_id = None
    admin_role_key = ""
    connection_id = None
    route_ids: tuple[UUID, UUID] = ()
    route_keys: tuple[str, str] = ()
    try:
        async with AsyncSessionLocal() as db:
            suffix = uuid4().hex
            profile = AgentProfile(
                name="Web chat v2 integration agent",
                slug=f"web-chat-v2-agent-{suffix}",
                version=1,
                is_active=True,
                is_public=True,
                retention_days=30,
                prompt_identity="test",
                prompt_domain="test",
                prompt_guardrails="test",
                unauthorized_message="unauthorized",
                error_message="error",
            )
            connection = ChannelConnection(
                name="Web chat v2",
                slug=f"web-chat-v2-{suffix}",
                channel="web",
                settings_json={},
                is_active=True,
            )
            admin_role_key = f"web-chat-v2-role-{suffix}"[:40]
            admin_role = AdminRole(
                key=admin_role_key,
                name="Web chat v2 operator",
                permissions=["conversations.manage"],
                is_active=True,
                is_system=False,
            )
            db.add_all([profile, connection, admin_role])
            await db.flush()
            admin = AdminUser(
                email=f"web-chat-v2-{suffix}@example.invalid",
                hashed_password="not-used",
                name="Web chat v2 operator",
                role=admin_role.key,
                is_active=True,
            )
            db.add(admin)
            await db.flush()
            route_keys = (f"web-v2-a-{suffix}", f"web-v2-b-{suffix}")
            routes = [
                ChannelAgentRoute(
                    channel="web",
                    route_key=route_key,
                    channel_connection_id=connection.id,
                    agent_id=profile.id,
                    is_active=True,
                )
                for route_key in route_keys
            ]
            db.add_all(routes)
            await db.commit()
            agent_id = profile.id
            admin_id = admin.id
            connection_id = connection.id
            route_ids = (routes[0].id, routes[1].id)
            yield _WebRouteGraph(
                agent_id=profile.id,
                admin_id=admin.id,
                admin_role_key=admin_role.key,
                connection_id=connection.id,
                route_ids=route_ids,
                route_keys=route_keys,
            )
    finally:
        async with AsyncSessionLocal() as db:
            if agent_id is not None:
                conversations = list(
                    (
                        (
                            await db.execute(
                                select(ChatConversation).where(
                                    ChatConversation.agent_id == agent_id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                )
                principal_ids = {row.principal_id for row in conversations}
                if conversations:
                    await db.execute(
                        delete(ChatConversation).where(
                            ChatConversation.id.in_([row.id for row in conversations])
                        )
                    )
                if principal_ids:
                    await db.execute(
                        delete(Principal).where(Principal.id.in_(principal_ids))
                    )
            if route_ids:
                await db.execute(
                    delete(ChannelAgentRoute).where(ChannelAgentRoute.id.in_(route_ids))
                )
            if connection_id is not None:
                await db.execute(
                    delete(ChannelConnection).where(
                        ChannelConnection.id == connection_id
                    )
                )
            if agent_id is not None:
                await db.execute(
                    delete(AgentProfile).where(AgentProfile.id == agent_id)
                )
            if admin_id is not None:
                await db.execute(delete(AdminUser).where(AdminUser.id == admin_id))
            if admin_role_key:
                await db.execute(
                    delete(AdminRole).where(AdminRole.key == admin_role_key)
                )
            await db.commit()
        await engine.dispose()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _message_payload(*, session_id: UUID, message_id: UUID, route_key: str) -> dict:
    return {
        "session_id": str(session_id),
        "client_message_id": str(message_id),
        "route_key": route_key,
        "content": "I need a durable website conversation",
        "locale": "es-AR",
        "consent": {"granted": True, "version": "privacy-v1"},
    }


@pytest.mark.asyncio
async def test_durable_message_history_events_scope_and_reset(web_route_graph):
    session_id = uuid4()
    next_session_id = uuid4()
    first_message_id = uuid4()
    second_message_id = uuid4()
    first_route, second_route = web_route_graph.route_keys
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        first_payload = _message_payload(
            session_id=session_id,
            message_id=first_message_id,
            route_key=first_route,
        )
        first = await client.post("/internal/v2/web/messages", json=first_payload)
        duplicate = await client.post(
            "/internal/v2/web/messages",
            json=first_payload,
        )
        conflict_payload = {**first_payload, "content": "Different content"}
        conflict = await client.post(
            "/internal/v2/web/messages",
            json=conflict_payload,
        )
        second = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(
                session_id=session_id,
                message_id=second_message_id,
                route_key=first_route,
            ),
        )
        async with AsyncSessionLocal() as db:
            conversation = (
                (
                    await db.execute(
                        select(ChatConversation).where(
                            ChatConversation.agent_id == web_route_graph.agent_id,
                            ChatConversation.external_thread_id == str(session_id),
                        )
                    )
                )
                .scalars()
                .one()
            )
            await ConversationEventService().publish(
                db,
                conversation_id=conversation.id,
                agent_id=web_route_graph.agent_id,
                event_type="chat.execution.changed",
                visibility=ConversationEventVisibility.INTERNAL,
                payload={"secret": "must-not-cross-the-private-boundary"},
            )
            await db.commit()
        history = await client.get(
            "/internal/v2/web/history",
            params={"session_id": str(session_id), "route_key": first_route},
        )
        first_events = await client.get(
            "/internal/v2/web/events",
            params={
                "session_id": str(session_id),
                "route_key": first_route,
                "after": 0,
                "limit": 1,
            },
        )
        second_events = await client.get(
            "/internal/v2/web/events",
            params={
                "session_id": str(session_id),
                "route_key": first_route,
                "after": 1,
                "limit": 10,
            },
        )
        cross_route = await client.get(
            "/internal/v2/web/history",
            params={"session_id": str(session_id), "route_key": second_route},
        )
        unavailable_route = await client.get(
            "/internal/v2/web/history",
            params={"session_id": str(session_id), "route_key": "missing-route"},
        )
        reset = await client.post(
            "/internal/v2/web/session/reset",
            json={
                "session_id": str(session_id),
                "next_session_id": str(next_session_id),
                "route_key": first_route,
                "consent": {"granted": True, "version": "privacy-v1"},
            },
        )
        closed_message = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(
                session_id=session_id,
                message_id=uuid4(),
                route_key=first_route,
            ),
        )
        replacement_history = await client.get(
            "/internal/v2/web/history",
            params={"session_id": str(next_session_id), "route_key": first_route},
        )
        repeated_reset = await client.post(
            "/internal/v2/web/session/reset",
            json={
                "session_id": str(session_id),
                "next_session_id": str(next_session_id),
                "route_key": first_route,
                "consent": {"granted": True, "version": "privacy-v1"},
            },
        )

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["event_cursor"] == first.json()["event_cursor"]
    assert conflict.status_code == 409
    assert second.status_code == 202
    assert history.status_code == 200
    assert [item["client_message_id"] for item in history.json()["messages"]] == [
        str(first_message_id),
        str(second_message_id),
    ]
    assert history.json()["latest_event_id"] == 3
    assert first_events.json()["has_more"] is True
    assert first_events.json()["next_cursor"] == 1
    assert second_events.json()["next_cursor"] == 2
    assert second_events.json()["has_more"] is False
    for event in first_events.json()["events"] + second_events.json()["events"]:
        assert "execution_id" not in event["payload"]
        assert "message_id" in event["payload"]
        assert event["schema_version"] == "2"
    assert cross_route.status_code == 404
    assert unavailable_route.status_code == 503
    assert reset.status_code == 200
    assert closed_message.status_code == 423
    assert replacement_history.status_code == 200
    assert replacement_history.json()["messages"] == []
    assert replacement_history.json()["latest_event_id"] == 0
    assert repeated_reset.status_code == 200
    assert repeated_reset.json() == reset.json()

    async with AsyncSessionLocal() as db:
        old_conversation = (
            (
                await db.execute(
                    select(ChatConversation).where(
                        ChatConversation.agent_id == web_route_graph.agent_id,
                        ChatConversation.external_thread_id == str(session_id),
                    )
                )
            )
            .scalars()
            .one()
        )
        executions = list(
            (
                (
                    await db.execute(
                        select(ChatExecution).where(
                            ChatExecution.conversation_id == old_conversation.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        )
        close_event = (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == old_conversation.id,
                        ConversationEvent.event_type == "chat.conversation.closed",
                    )
                )
            )
            .scalars()
            .one()
        )

    assert old_conversation.status == "closed"
    assert old_conversation.control_mode == "closed"
    assert old_conversation.control_version == 1
    assert {execution.status for execution in executions} == {"cancelled"}
    assert close_event.visibility == "public"


@pytest.mark.asyncio
async def test_human_and_paused_web_input_is_durable_without_execution(
    web_route_graph,
):
    session_id = uuid4()
    automated_message_id = uuid4()
    human_message_id = uuid4()
    paused_message_id = uuid4()
    route_key = web_route_graph.route_keys[0]
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        automated = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(
                session_id=session_id,
                message_id=automated_message_id,
                route_key=route_key,
            ),
        )
        async with AsyncSessionLocal() as db:
            conversation = (
                (
                    await db.execute(
                        select(ChatConversation).where(
                            ChatConversation.agent_id == web_route_graph.agent_id,
                            ChatConversation.external_thread_id == str(session_id),
                        )
                    )
                )
                .scalars()
                .one()
            )
            conversation.control_mode = "human"
            conversation.control_version += 1
            conversation.assigned_admin_id = web_route_graph.admin_id
            await db.commit()

        human_payload = _message_payload(
            session_id=session_id,
            message_id=human_message_id,
            route_key=route_key,
        )
        human = await client.post(
            "/internal/v2/web/messages",
            json=human_payload,
        )
        duplicate = await client.post(
            "/internal/v2/web/messages",
            json=human_payload,
        )
        conflict = await client.post(
            "/internal/v2/web/messages",
            json={**human_payload, "content": "Different human input"},
        )

        async with AsyncSessionLocal() as db:
            conversation = (
                (
                    await db.execute(
                        select(ChatConversation).where(
                            ChatConversation.agent_id == web_route_graph.agent_id,
                            ChatConversation.external_thread_id == str(session_id),
                        )
                    )
                )
                .scalars()
                .one()
            )
            conversation.control_mode = "paused"
            conversation.control_version += 1
            await db.commit()

        paused = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(
                session_id=session_id,
                message_id=paused_message_id,
                route_key=route_key,
            ),
        )
        async with AsyncSessionLocal() as db:
            conversation = (
                (
                    await db.execute(
                        select(ChatConversation).where(
                            ChatConversation.agent_id == web_route_graph.agent_id,
                            ChatConversation.external_thread_id == str(session_id),
                        )
                    )
                )
                .scalars()
                .one()
            )
            conversation.control_mode = "automated"
            conversation.control_version += 1
            conversation.assigned_admin_id = None
            await db.commit()
        duplicate_after_resume = await client.post(
            "/internal/v2/web/messages",
            json=human_payload,
        )

    assert automated.status_code == 202
    assert human.status_code == 202
    assert human.json()["status"] == "accepted"
    assert human.json()["duplicate"] is False
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["event_cursor"] == human.json()["event_cursor"]
    assert conflict.status_code == 409
    assert paused.status_code == 202
    assert paused.json()["status"] == "accepted"
    assert duplicate_after_resume.status_code == 202
    assert duplicate_after_resume.json()["duplicate"] is True
    assert duplicate_after_resume.json()["event_cursor"] == human.json()["event_cursor"]

    async with AsyncSessionLocal() as db:
        conversation = (
            (
                await db.execute(
                    select(ChatConversation).where(
                        ChatConversation.agent_id == web_route_graph.agent_id,
                        ChatConversation.external_thread_id == str(session_id),
                    )
                )
            )
            .scalars()
            .one()
        )
        executions = list(
            (
                (
                    await db.execute(
                        select(ChatExecution).where(
                            ChatExecution.conversation_id == conversation.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        )
        messages = list(
            (
                (
                    await db.execute(
                        select(ChatMessage).where(
                            ChatMessage.conversation_id == conversation.id,
                            ChatMessage.client_message_id.in_(
                                (str(human_message_id), str(paused_message_id))
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
        )

    assert [execution.client_message_id for execution in executions] == [
        str(automated_message_id)
    ]
    assert {message.client_message_id for message in messages} == {
        str(human_message_id),
        str(paused_message_id),
    }
    assert {message.status for message in messages} == {"completed"}


@pytest.mark.asyncio
async def test_web_takeover_publishes_only_sanitized_public_control_state(
    web_route_graph,
):
    session_id = uuid4()
    route_key = web_route_graph.route_keys[0]
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        accepted = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(
                session_id=session_id,
                message_id=uuid4(),
                route_key=route_key,
            ),
        )
        assert accepted.status_code == 202

        async with AsyncSessionLocal() as db:
            conversation = (
                (
                    await db.execute(
                        select(ChatConversation).where(
                            ChatConversation.agent_id == web_route_graph.agent_id,
                            ChatConversation.external_thread_id == str(session_id),
                        )
                    )
                )
                .scalars()
                .one()
            )
            await ConversationControlService().transition(
                db,
                conversation_id=conversation.id,
                agent_id=web_route_graph.agent_id,
                actor_admin_id=web_route_graph.admin_id,
                target_mode=ConversationControlMode.HUMAN,
                expected_version=conversation.control_version,
                reason="private reason that must not cross the web boundary",
            )
            await db.commit()

        events = await client.get(
            "/internal/v2/web/events",
            params={
                "session_id": str(session_id),
                "route_key": route_key,
                "after": 0,
            },
        )

    assert events.status_code == 200
    control_event = next(
        item
        for item in events.json()["events"]
        if item["event_type"] == "chat.control.changed"
    )
    assert control_event["payload"] == {"mode": "human", "status": "active"}
    assert "admin" not in str(control_event["payload"])
    assert "reason" not in str(control_event["payload"])
