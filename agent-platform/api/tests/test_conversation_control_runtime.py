"""Focused runtime fencing tests for human conversation control."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.platform import (
    ChannelIdentity,
    ChatConversation,
    ChatExecution,
    ChatMessage,
    Principal,
)
from app.schemas.conversation_control import ConversationControlMode
from app.schemas.executions import InternalExecutionRequest, TranscriptConsent
from app.services.agent_loop import run_agent_loop
from app.services.chat_application import AgentNotReady, ChatApplicationService
from app.services.conversation_control import (
    AutomationBlockedError,
    ControlVersionConflictError,
    ConversationControlService,
)
from app.services.pipeline import PipelineService


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else []


class _ControlRuntimeDb:
    def __init__(self, *, identity: ChannelIdentity, conversation: ChatConversation):
        self.rows = [identity, conversation]
        self.commits = 0

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is ChatExecution:
            return _Result(None)
        if entity is ChannelIdentity:
            return _Result(self._first(ChannelIdentity))
        if entity is ChatConversation:
            return _Result(self._first(ChatConversation))
        if entity is ChatMessage:
            messages = [
                row
                for row in self.rows
                if isinstance(row, ChatMessage) and row.status == "completed"
            ]
            return _Result(messages)
        return _Result(None)

    def add(self, row):
        if row.id is None:
            row.id = uuid4()
        self.rows.append(row)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    def _first(self, model):
        return next((row for row in self.rows if isinstance(row, model)), None)


def _profile() -> AgentProfile:
    return AgentProfile(
        id=uuid4(),
        name="Control Test Agent",
        slug=f"control-test-{uuid4().hex[:8]}",
        version=1,
        is_active=True,
        is_public=True,
        retention_days=30,
        prompt_identity="identity",
        prompt_domain="domain",
        prompt_guardrails="guardrails",
        unauthorized_message="unauthorized",
        error_message="error",
        created_by="test",
    )


def _web_runtime_fixture(*, control_mode: str, control_version: int):
    profile = _profile()
    route_key = "control-runtime"
    session_id = uuid4()
    route_id = uuid4()
    identity = ChannelIdentity(
        id=uuid4(),
        principal_id=uuid4(),
        channel="web",
        route_key=route_key,
        external_subject=str(session_id),
        verified=True,
    )
    conversation = ChatConversation(
        id=uuid4(),
        agent_id=profile.id,
        principal_id=identity.principal_id,
        channel="web",
        external_thread_id=str(session_id),
        route_key=route_key,
        channel_route_id=route_id,
        transcript_consent=True,
        consent_version="test-v1",
        control_mode=control_mode,
        control_version=control_version,
        assigned_admin_id=uuid4() if control_mode == "human" else None,
    )
    runtime = SimpleNamespace(
        profile=profile,
        config=SimpleNamespace(
            history_message_limit=20,
            history_cache_ttl_seconds=0,
        ),
    )
    resolved_route = SimpleNamespace(
        runtime=runtime,
        route=SimpleNamespace(id=route_id),
    )
    request = InternalExecutionRequest(
        request_id=uuid4(),
        session_id=session_id,
        input="I need help",
        consent=TranscriptConsent(granted=True, version="test-v1"),
        route_key=route_key,
    )
    return (
        _ControlRuntimeDb(identity=identity, conversation=conversation),
        conversation,
        resolved_route,
        request,
    )


def _mock_loop_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.agent_loop.knowledge_service.build_all_knowledge",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "app.services.agent_loop.rag_retrieval_service.search",
        AsyncMock(return_value=[]),
    )


@pytest.mark.asyncio
async def test_agent_loop_checks_control_before_llm(monkeypatch):
    _mock_loop_dependencies(monkeypatch)
    guard = AsyncMock(side_effect=AutomationBlockedError("paused"))
    create = AsyncMock()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with (
        patch("openai.AsyncOpenAI", return_value=client),
        pytest.raises(AutomationBlockedError),
    ):
        await run_agent_loop(
            user_message="hello",
            conversation_history=[],
            available_tools=[],
            tool_configs={},
            profile=None,
            user_id=None,
            phone="test",
            request_id="guard-before-llm",
            db=object(),
            automation_guard=guard,
        )

    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_loop_discards_final_result_after_epoch_change(monkeypatch):
    _mock_loop_dependencies(monkeypatch)
    guard = AsyncMock(
        side_effect=[None, ControlVersionConflictError(expected=2, actual=3)]
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="stale answer", tool_calls=None)
                )
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with (
        patch("openai.AsyncOpenAI", return_value=client),
        pytest.raises(ControlVersionConflictError),
    ):
        await run_agent_loop(
            user_message="hello",
            conversation_history=[],
            available_tools=[],
            tool_configs={},
            profile=None,
            user_id=None,
            phone="test",
            request_id="guard-final-result",
            db=object(),
            automation_guard=guard,
        )

    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_loop_does_not_invoke_tool_after_epoch_change(monkeypatch):
    _mock_loop_dependencies(monkeypatch)
    guard = AsyncMock(
        side_effect=[None, ControlVersionConflictError(expected=4, actual=5)]
    )
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="safe_tool", arguments="{}"),
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=[tool_call])
                )
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    invoke = AsyncMock()
    monkeypatch.setattr(
        "app.services.agent_loop.tool_registry.get", lambda _name: object()
    )
    monkeypatch.setattr("app.services.agent_loop.tool_registry.invoke", invoke)

    with (
        patch("openai.AsyncOpenAI", return_value=client),
        pytest.raises(ControlVersionConflictError),
    ):
        await run_agent_loop(
            user_message="hello",
            conversation_history=[],
            available_tools=[{"tool_name": "safe_tool", "description": "test"}],
            tool_configs={"safe_tool": {"params_schema": {}}},
            profile=None,
            user_id=None,
            phone="test",
            request_id="guard-tool",
            db=object(),
            automation_guard=guard,
        )

    invoke.assert_not_awaited()


@pytest.mark.parametrize("control_mode", ["paused", "human"])
@pytest.mark.asyncio
async def test_web_persists_inbound_but_skips_llm_when_automation_is_blocked(
    monkeypatch,
    control_mode,
):
    db, conversation, resolved_route, request = _web_runtime_fixture(
        control_mode=control_mode,
        control_version=7,
    )
    loop = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_application.agent_runtime_resolver.resolve_route",
        AsyncMock(return_value=resolved_route),
    )
    monkeypatch.setattr("app.services.chat_application.run_agent_loop", loop)

    with pytest.raises(AgentNotReady, match="not active"):
        await ChatApplicationService().execute_web(db, request)

    inbound = next(row for row in db.rows if isinstance(row, ChatMessage))
    execution = next(row for row in db.rows if isinstance(row, ChatExecution))
    assert inbound.conversation_id == conversation.id
    assert inbound.role == "user"
    assert inbound.status == "completed"
    assert execution.control_version == 7
    assert execution.status == "blocked"
    assert execution.error_code == "conversation_control_changed"
    assert not any(
        isinstance(row, ChatMessage) and row.role == "assistant" for row in db.rows
    )
    loop.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_discards_automatic_output_when_takeover_occurs_during_loop(
    monkeypatch,
):
    db, conversation, resolved_route, request = _web_runtime_fixture(
        control_mode="automated",
        control_version=4,
    )

    async def simulate_takeover(**kwargs):
        conversation.control_mode = "human"
        conversation.control_version = 5
        conversation.assigned_admin_id = uuid4()
        await kwargs["automation_guard"]()
        raise AssertionError("the stale loop result must not be returned")

    monkeypatch.setattr(
        "app.services.chat_application.agent_runtime_resolver.resolve_route",
        AsyncMock(return_value=resolved_route),
    )
    monkeypatch.setattr(
        "app.services.chat_application.tool_policy_service.available_tools",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.chat_application.run_agent_loop",
        AsyncMock(side_effect=simulate_takeover),
    )

    with pytest.raises(AgentNotReady, match="changed during execution"):
        await ChatApplicationService().execute_web(db, request)

    execution = next(row for row in db.rows if isinstance(row, ChatExecution))
    assert execution.control_version == 4
    assert execution.status == "blocked"
    assert not any(
        isinstance(row, ChatMessage) and row.role == "assistant" for row in db.rows
    )


@pytest.mark.asyncio
async def test_whatsapp_human_control_persists_inbound_without_automation(
    monkeypatch,
):
    from app.services import pipeline as module

    class FakeDb:
        commits = 0
        rollbacks = 0

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    class FakeSession:
        db = FakeDb()

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *_args):
            return False

    profile = _profile()
    route_id = uuid4()
    conversation = SimpleNamespace(id=uuid4(), control_version=5)
    runtime = SimpleNamespace(
        profile=profile,
        config=SimpleNamespace(
            history_message_limit=20,
            history_cache_ttl_seconds=0,
        ),
    )
    guard = AsyncMock(side_effect=AutomationBlockedError("human control"))
    inbound = AsyncMock()
    loop = AsyncMock()
    exchange = AsyncMock()
    notification = AsyncMock()

    monkeypatch.setattr(module, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(module.whatsapp_service, "mark_as_read", AsyncMock())
    monkeypatch.setattr(module.whatsapp_service, "show_typing", AsyncMock())
    monkeypatch.setattr(
        module.chat_application_service,
        "load_whatsapp_context",
        AsyncMock(return_value=([], None, conversation)),
    )
    monkeypatch.setattr(
        module.governance_service,
        "check_access",
        AsyncMock(
            return_value=SimpleNamespace(
                allowed=True,
                user={"user_id": str(uuid4()), "name": "Lead"},
            )
        ),
    )
    monkeypatch.setattr(
        module.chat_application_service,
        "record_whatsapp_inbound",
        inbound,
    )
    monkeypatch.setattr(
        module.chat_application_service,
        "record_whatsapp_exchange",
        exchange,
    )
    monkeypatch.setattr(
        module.chat_application_service,
        "record_whatsapp_notification",
        notification,
    )
    monkeypatch.setattr(module, "run_agent_loop", loop)
    service = PipelineService()
    monkeypatch.setattr(service, "_build_automation_guard", lambda **_kwargs: guard)

    await service._process_locked(
        phone="5493870000000",
        content="I need a person.",
        message_id="wamid.human",
        input_type="text",
        audio_media_id=None,
        interactive_id=None,
        quoted_id=None,
        redis=None,
        request_id="inbound-human-control",
        start=0.0,
        resolved_runtime=runtime,
        whatsapp_connection=SimpleNamespace(),
        route_key="whatsapp-human",
        channel_route_id=route_id,
        propagate_errors=True,
        notify_on_error=True,
    )

    inbound.assert_awaited_once_with(
        FakeSession.db,
        conversation=conversation,
        request_id="inbound-human-control",
        content="I need a person.",
    )
    assert FakeSession.db.commits == 2
    loop.assert_not_awaited()
    exchange.assert_not_awaited()
    notification.assert_not_awaited()
    module.whatsapp_service.show_typing.assert_not_awaited()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_session_observes_takeover_committed_by_another_session():
    """A long-lived runtime session must not reuse a stale identity-map snapshot."""
    service = ConversationControlService()
    principal_id = None

    try:
        async with AsyncSessionLocal() as setup_db:
            agent = (
                (
                    await setup_db.execute(
                        select(AgentProfile).where(AgentProfile.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            admin = (
                (
                    await setup_db.execute(
                        select(AdminUser).where(AdminUser.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            assert agent is not None
            assert admin is not None

            principal = Principal(display_name="Runtime guard integration test")
            setup_db.add(principal)
            await setup_db.flush()
            conversation = ChatConversation(
                agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                external_thread_id=f"runtime-guard-{uuid4()}",
                route_key="runtime-guard-integration",
                transcript_consent=True,
                consent_version="test-v1",
            )
            setup_db.add(conversation)
            await setup_db.flush()
            principal_id = principal.id
            conversation_id = conversation.id
            agent_id = agent.id
            admin_id = admin.id
            await setup_db.commit()

        async with AsyncSessionLocal() as runtime_db:
            snapshot = await service.get_snapshot(
                runtime_db,
                conversation_id=conversation_id,
                agent_id=agent_id,
            )
            assert snapshot.control_version == 0

            async with AsyncSessionLocal() as operator_db:
                await service.transition(
                    operator_db,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    actor_admin_id=admin_id,
                    target_mode=ConversationControlMode.HUMAN,
                    expected_version=0,
                )
                await operator_db.commit()

            with pytest.raises(ControlVersionConflictError):
                await service.assert_automation_allowed(
                    runtime_db,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    expected_version=0,
                )
    finally:
        if principal_id is not None:
            async with AsyncSessionLocal() as cleanup_db:
                await cleanup_db.execute(
                    delete(Principal).where(Principal.id == principal_id)
                )
                await cleanup_db.commit()
        await engine.dispose()
