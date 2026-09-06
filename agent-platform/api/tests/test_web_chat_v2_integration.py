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
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution, Principal
from app.routers.web_chat_v2 import router
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _WebRouteGraph:
    agent_id: UUID
    connection_id: UUID
    route_ids: tuple[UUID, UUID]
    route_keys: tuple[str, str]


@pytest.fixture
async def web_route_graph():
    agent_id = None
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
            db.add_all([profile, connection])
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
            connection_id = connection.id
            route_ids = (routes[0].id, routes[1].id)
            yield _WebRouteGraph(
                agent_id=profile.id,
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
