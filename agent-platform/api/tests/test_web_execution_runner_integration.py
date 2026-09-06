"""PostgreSQL integration coverage for the durable web execution runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.services.agent_loop import AgentLoopResult
from app.services.web_execution_queue import WebExecutionQueueService
from app.services.web_execution_runner import (
    WebExecutionRunner,
    WebExecutionRunStatus,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _RunnerGraph:
    agent: AgentProfile
    route: ChannelAgentRoute
    connection_id: UUID
    conversation_id: UUID
    principal_id: UUID


@pytest.fixture
async def runner_graph():
    graph = None
    try:
        async with AsyncSessionLocal() as db:
            suffix = uuid4().hex
            agent = AgentProfile(
                name="Web execution runner agent",
                slug=f"web-runner-agent-{suffix}",
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
                name="Web runner",
                slug=f"web-runner-{suffix}",
                channel="web",
                settings_json={},
                is_active=True,
            )
            principal = Principal(kind="anonymous", is_active=True)
            db.add_all([agent, connection, principal])
            await db.flush()
            route = ChannelAgentRoute(
                channel="web",
                route_key=f"web-runner-route-{suffix}",
                channel_connection_id=connection.id,
                agent_id=agent.id,
                is_active=True,
            )
            db.add(route)
            await db.flush()
            conversation = ChatConversation(
                agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                external_thread_id=str(uuid4()),
                route_key=route.route_key,
                channel_route_id=route.id,
                transcript_consent=True,
                consent_version="privacy-v1",
            )
            db.add(conversation)
            await db.flush()
            db.add(
                ChatMessage(
                    conversation_id=conversation.id,
                    client_message_id="previous-message",
                    role="assistant",
                    content="Previous context",
                    status="completed",
                )
            )
            await db.commit()
            graph = _RunnerGraph(
                agent=agent,
                route=route,
                connection_id=connection.id,
                conversation_id=conversation.id,
                principal_id=principal.id,
            )
            yield graph
    finally:
        async with AsyncSessionLocal() as db:
            if graph is not None:
                await db.execute(
                    delete(ChatConversation).where(
                        ChatConversation.id == graph.conversation_id
                    )
                )
                await db.execute(
                    delete(Principal).where(Principal.id == graph.principal_id)
                )
                await db.execute(
                    delete(ChannelAgentRoute).where(
                        ChannelAgentRoute.id == graph.route.id
                    )
                )
                await db.execute(
                    delete(ChannelConnection).where(
                        ChannelConnection.id == graph.connection_id
                    )
                )
                await db.execute(
                    delete(AgentProfile).where(AgentProfile.id == graph.agent.id)
                )
                await db.commit()
        await engine.dispose()


class _RuntimeResolver:
    def __init__(self, graph: _RunnerGraph):
        self._graph = graph

    async def resolve_route(self, _db, channel, route_key, *, require_public):
        assert channel == "web"
        assert route_key == self._graph.route.route_key
        assert require_public is True
        return SimpleNamespace(
            route=self._graph.route,
            runtime=SimpleNamespace(
                profile=self._graph.agent,
                config=SimpleNamespace(history_message_limit=20),
            ),
        )


class _NoToolsPolicy:
    async def available_tools(self, _db, context, _registered_tools):
        assert context.channel == "web"
        assert context.scopes == set()
        return []


def _runner(graph, agent_loop, *, lease_duration=timedelta(minutes=5)):
    return WebExecutionRunner(
        worker_id="web-runner-integration",
        lease_duration=lease_duration,
        runtime_resolver=_RuntimeResolver(graph),
        policy_service=_NoToolsPolicy(),
        agent_loop=agent_loop,
        session_factory=AsyncSessionLocal,
    )


async def _enqueue(graph, client_message_id):
    async with AsyncSessionLocal() as db:
        result = await WebExecutionQueueService().enqueue(
            db,
            conversation_id=graph.conversation_id,
            agent_id=graph.agent.id,
            client_message_id=client_message_id,
            content="Current request",
            locale="es-AR",
        )
        await db.commit()
        return result.execution.id, result.inbound_message.id


@pytest.mark.asyncio
async def test_runner_executes_neutral_context_and_persists_public_completion(
    runner_graph,
):
    execution_id, inbound_id = await _enqueue(runner_graph, "runner-success")

    async def agent_loop(**kwargs):
        assert kwargs["user_message"] == "Current request"
        assert kwargs["conversation_history"] == [
            {"role": "assistant", "content": "Previous context"}
        ]
        assert kwargs["execution_context"].agent_id == str(runner_graph.agent.id)
        assert kwargs["execution_context"].conversation_id == str(
            runner_graph.conversation_id
        )
        await kwargs["automation_guard"]()
        return AgentLoopResult(
            response_text="Durable answer",
            tools_used=[],
            status="success",
        )

    runner = _runner(runner_graph, agent_loop)
    assert await runner.run_once() is True

    async with AsyncSessionLocal() as db:
        execution = await db.get(ChatExecution, execution_id)
        inbound = await db.get(ChatMessage, inbound_id)
        output = await db.get(ChatMessage, execution.output_message_id)
        completed_event = (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id
                        == runner_graph.conversation_id,
                        ConversationEvent.event_type == "chat.message.completed",
                    )
                )
            )
            .scalars()
            .one()
        )

    assert execution.status == "completed"
    assert inbound.status == "completed"
    assert output.content == "Durable answer"
    assert output.role == "assistant"
    assert completed_event.visibility == "public"
    assert completed_event.payload_json["content"] == "Durable answer"


@pytest.mark.asyncio
async def test_runner_discards_output_when_control_changes_during_execution(
    runner_graph,
):
    execution_id, _ = await _enqueue(runner_graph, "runner-takeover")

    async def agent_loop(**kwargs):
        await kwargs["automation_guard"]()
        async with AsyncSessionLocal() as db:
            conversation = await db.get(
                ChatConversation,
                runner_graph.conversation_id,
                with_for_update=True,
            )
            conversation.control_mode = "paused"
            conversation.control_version += 1
            await db.commit()
        return AgentLoopResult(response_text="Must not publish", status="success")

    result = await _runner(runner_graph, agent_loop).run_once()
    assert result is True

    async with AsyncSessionLocal() as db:
        execution = await db.get(ChatExecution, execution_id)
        output = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == runner_graph.conversation_id,
                    ChatMessage.content == "Must not publish",
                )
            )
        ).scalar_one_or_none()

    assert execution.status == "blocked"
    assert execution.error_code == "conversation_control_changed"
    assert output is None


@pytest.mark.asyncio
async def test_runner_persists_safe_failure_without_exposing_model_text(runner_graph):
    execution_id, _ = await _enqueue(runner_graph, "runner-failed")

    async def agent_loop(**kwargs):
        await kwargs["automation_guard"]()
        return AgentLoopResult(
            response_text="Provider detail that must not become a chat message",
            status="error",
        )

    assert await _runner(runner_graph, agent_loop).run_once() is True

    async with AsyncSessionLocal() as db:
        execution = await db.get(ChatExecution, execution_id)
        leaked_output = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == runner_graph.conversation_id,
                    ChatMessage.content
                    == "Provider detail that must not become a chat message",
                )
            )
        ).scalar_one_or_none()
        failure_event = (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id
                        == runner_graph.conversation_id,
                        ConversationEvent.event_type == "chat.message.failed",
                    )
                )
            )
            .scalars()
            .one()
        )

    assert execution.status == "failed"
    assert execution.error_code == "agent_execution_failed"
    assert leaked_output is None
    assert failure_event.payload_json["error_code"] == "agent_execution_failed"
    assert "Provider detail" not in str(failure_event.payload_json)


@pytest.mark.asyncio
async def test_runner_blocks_an_expired_lease_before_agent_execution(runner_graph):
    execution_id, _ = await _enqueue(runner_graph, "runner-expired")
    called = False

    async def agent_loop(**_kwargs):
        nonlocal called
        called = True
        return AgentLoopResult(response_text="Must not execute", status="success")

    runner = _runner(runner_graph, agent_loop)
    claim = await runner.claim_once()
    assert claim is not None
    async with AsyncSessionLocal() as db:
        execution = await db.get(ChatExecution, execution_id)
        execution.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    result = await runner.execute_claim(claim)

    async with AsyncSessionLocal() as db:
        execution = await db.get(ChatExecution, execution_id)
    assert result.status == WebExecutionRunStatus.BLOCKED
    assert execution.status == "blocked"
    assert execution.error_code == "stale_execution_lease"
    assert called is False
