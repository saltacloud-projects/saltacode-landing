"""Regression coverage for persisted runtime, encrypted connections, and routing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.bootstrap import bootstrap_operational_config
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import (
    AgentRuntimeConfig,
    ChannelAgentRoute,
    ChannelConnection,
    ProviderConnection,
)
from app.models.platform import ChatConversation, ChatExecution, ChatMessage
from app.routers.admin.agent_runtime import patch_runtime, router
from app.routers.admin.promptlab import PromptPreviewRequest, prompt_preview
from app.schemas.agent_runtime import (
    AgentRuntimeUpdate,
    ChannelConnectionCreate,
    ProviderConnectionCreate,
    ProviderConnectionOut,
)
from app.schemas.executions import InternalExecutionRequest, TranscriptConsent
from app.services.agent_loop import run_agent_loop
from app.services.agent_runtime import (
    AgentRuntimeResolver,
    AgentRuntimeUnavailable,
    ResolvedAgentRoute,
    ResolvedAgentRuntime,
)
from app.services.chat_application import AgentNotReady, ChatApplicationService
from app.services.credentials import CredentialCipher


class _Result:
    def __init__(self, row=None):
        self.row = row

    def one_or_none(self):
        return self.row

    def scalar_one_or_none(self):
        return self.row


class _SequenceDb:
    def __init__(self, *rows):
        self.rows = list(rows)

    async def execute(self, _statement):
        return _Result(self.rows.pop(0))


class _MemoryDb:
    def __init__(self):
        self.rows = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return _Result(
            next((row for row in self.rows if isinstance(row, entity)), None)
        )

    def add(self, row):
        if row.id is None:
            row.id = uuid4()
        self.rows.append(row)

    async def flush(self):
        return None


def _profile(*, active=True, public=True):
    now = datetime.now(timezone.utc)
    return AgentProfile(
        id=uuid4(),
        name="Agent",
        slug=f"agent-{uuid4().hex[:6]}",
        version=1,
        is_active=active,
        is_public=public,
        retention_days=30,
        description=None,
        prompt_identity="identity",
        prompt_domain="domain",
        prompt_guardrails="guardrails",
        unauthorized_message="no",
        error_message="error",
        created_by="test",
        created_at=now,
        updated_at=now,
    )


def _runtime(profile, provider):
    return AgentRuntimeConfig(
        id=uuid4(),
        agent_id=profile.id,
        provider_connection_id=provider.id,
        chat_model="model-a",
        transcription_model="transcribe-a",
        temperature=0.5,
        max_output_tokens=2000,
        max_iterations=12,
        max_tool_calls=25,
        loop_timeout_seconds=150,
        tool_timeout_seconds=60,
        tool_result_max_chars=16000,
        history_message_limit=20,
        history_cache_ttl_seconds=300,
        summary_enabled=True,
        summary_trigger_messages=10,
        summary_max_chars=60000,
        rag_enabled=False,
        rag_retrieval_top_k=8,
        rag_min_relevance_score=0.35,
        rag_vector_weight=0.7,
        rag_lexical_weight=0.3,
    )


def test_route_key_is_optional_only_for_transition_and_strict_when_present():
    base = dict(
        request_id=uuid4(),
        session_id=uuid4(),
        input="hello",
        consent=TranscriptConsent(granted=True, version="v1"),
    )
    assert InternalExecutionRequest(**base).route_key is None
    assert (
        InternalExecutionRequest(**base, route_key="saltacode-landing").route_key
        == "saltacode-landing"
    )
    with pytest.raises(ValidationError):
        InternalExecutionRequest(**base, route_key="Invalid Route")


def test_admin_api_exposes_connections_runtime_and_profile_routes():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")
    contracts = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("/api/admin/provider-connections", "POST") in contracts
    assert ("/api/admin/provider-connections/{connection_id}/test", "POST") in contracts
    assert ("/api/admin/channel-connections", "POST") in contracts
    assert ("/api/admin/profiles/{agent_id}/runtime", "PATCH") in contracts
    assert ("/api/admin/profiles/{agent_id}/routes", "POST") in contracts
    assert (
        "/api/admin/profiles/{agent_id}/routes/{route_id}/deactivate",
        "POST",
    ) in contracts


def test_provider_credentials_are_encrypted_and_write_only(tmp_path, monkeypatch):
    key_file = tmp_path / "master.key"
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(
        "app.services.credentials.settings.credential_encryption_key_file",
        str(key_file),
    )
    cipher = CredentialCipher()
    token = cipher.encrypt({"api_key": "secret-value"})
    assert "secret-value" not in token
    assert cipher.decrypt(token) == {"api_key": "secret-value"}
    data = ProviderConnectionCreate(
        name="OpenAI", slug="openai", credentials={"api_key": "secret-value"}
    )
    assert "secret-value" not in repr(data)
    now = datetime.now(timezone.utc)
    row = ProviderConnection(
        id=uuid4(),
        name="OpenAI",
        slug="openai",
        provider_type="openai",
        settings_json={},
        encrypted_credentials=token,
        is_active=True,
        created_by="test",
        updated_by="test",
        created_at=now,
        updated_at=now,
    )
    assert ProviderConnectionOut.from_model(row).has_credentials is True
    assert "credentials" not in ProviderConnectionOut.model_fields
    with pytest.raises(ValidationError):
        ProviderConnectionCreate(
            name="OpenAI",
            slug="bad",
            credentials={"api_key": "ok", "unexpected": "forbidden"},
        )
    with pytest.raises(ValidationError):
        ProviderConnectionCreate(
            name="OpenAI",
            slug="bad-url",
            base_url="https://user:pass@example.test/v1?secret=yes",
        )
    with pytest.raises(ValidationError, match="must be stored in credentials"):
        ProviderConnectionCreate(
            name="OpenAI",
            slug="bad-settings",
            settings={"nested": {"api_key": "plaintext"}},
        )
    with pytest.raises(ValidationError):
        ChannelConnectionCreate(
            name="Web",
            slug="web",
            channel="web",
            credentials={"access_token": "a", "verify_token": "b", "app_secret": "c"},
        )


def test_rag_weights_must_form_a_normalized_policy():
    AgentRuntimeUpdate(rag_vector_weight=0.7, rag_lexical_weight=0.3)
    with pytest.raises(ValidationError, match="must sum to 1"):
        AgentRuntimeUpdate(rag_vector_weight=0.7, rag_lexical_weight=0.7)


@pytest.mark.asyncio
async def test_runtime_provider_can_be_cleared_explicitly():
    profile = _profile()
    provider = ProviderConnection(
        id=uuid4(),
        name="P",
        slug="p",
        provider_type="openai",
        settings_json={},
        encrypted_credentials="cipher",
        is_active=True,
    )
    runtime = _runtime(profile, provider)

    class RuntimeDb:
        async def get(self, model, _row_id):
            if model is AgentProfile:
                return profile
            raise AssertionError("Provider lookup is not expected when clearing it")

        async def execute(self, _statement):
            return _Result(runtime)

        async def flush(self):
            return None

    result = await patch_runtime(
        str(profile.id),
        AgentRuntimeUpdate(provider_connection_id=None),
        db=RuntimeDb(),
        admin=SimpleNamespace(email="admin@example.test"),
    )

    assert runtime.provider_connection_id is None
    assert result.provider_connection_id is None
    assert result.provider_ready is False


@pytest.mark.asyncio
async def test_resolver_isolates_route_and_fails_closed_for_inactive_agent(monkeypatch):
    profile = _profile()
    provider = ProviderConnection(
        id=uuid4(),
        name="P",
        slug="p",
        provider_type="openai",
        settings_json={},
        encrypted_credentials="cipher",
        is_active=True,
    )
    runtime = _runtime(profile, provider)
    connection = ChannelConnection(
        id=uuid4(),
        name="Web",
        slug="web",
        channel="web",
        settings_json={},
        is_active=True,
    )
    route = ChannelAgentRoute(
        id=uuid4(),
        channel="web",
        route_key="agent-a",
        channel_connection_id=connection.id,
        agent_id=profile.id,
        is_active=True,
    )
    monkeypatch.setattr(
        "app.services.agent_runtime.credential_cipher.decrypt",
        lambda _token: {"api_key": "request-scoped"},
    )
    resolved = await AgentRuntimeResolver().resolve_route(
        _SequenceDb((route, connection), (profile, runtime, provider)),
        "web",
        "agent-a",
        require_public=True,
    )
    assert resolved.runtime.profile.id == profile.id
    assert resolved.runtime.api_key == "request-scoped"

    profile_b = _profile()
    route_b = ChannelAgentRoute(
        id=uuid4(),
        channel="web",
        route_key="agent-b",
        channel_connection_id=connection.id,
        agent_id=profile_b.id,
        is_active=True,
    )
    resolved_b = await AgentRuntimeResolver().resolve_route(
        _SequenceDb(
            (route_b, connection), (profile_b, _runtime(profile_b, provider), provider)
        ),
        "web",
        "agent-b",
        require_public=True,
    )
    assert resolved_b.runtime.profile.id == profile_b.id
    assert resolved_b.runtime.profile.id != resolved.runtime.profile.id

    inactive = _profile(active=False)
    with pytest.raises(AgentRuntimeUnavailable, match="inactive"):
        await AgentRuntimeResolver().resolve_agent(
            _SequenceDb((inactive, _runtime(inactive, provider), provider)), inactive.id
        )
    with pytest.raises(AgentRuntimeUnavailable, match="unknown|not configured"):
        await AgentRuntimeResolver().resolve_agent(_SequenceDb(None), uuid4())


@pytest.mark.asyncio
async def test_conversation_rejects_cross_route_replay():
    route_a, route_b = uuid4(), uuid4()
    conversation = ChatConversation(
        id=uuid4(),
        agent_id=uuid4(),
        principal_id=uuid4(),
        channel="web",
        external_thread_id="session",
        route_key="site-a",
        channel_route_id=route_a,
        transcript_consent=True,
    )
    with pytest.raises(AgentNotReady, match="another route"):
        await ChatApplicationService()._resolve_conversation(
            _SequenceDb(conversation),
            agent_id=conversation.agent_id,
            principal_id=conversation.principal_id,
            channel="web",
            external_thread_id="session",
            consent_version="v1",
            route_key="site-b",
            channel_route_id=route_b,
        )


@pytest.mark.asyncio
async def test_completed_replay_validates_route_before_returning_outcome(monkeypatch):
    profile = _profile()
    provider = ProviderConnection(
        id=uuid4(),
        name="P",
        slug="p",
        provider_type="openai",
        settings_json={},
        encrypted_credentials="cipher",
        is_active=True,
    )
    runtime = ResolvedAgentRuntime(
        profile, _runtime(profile, provider), provider, "secret"
    )
    connection = ChannelConnection(
        id=uuid4(),
        name="Web",
        slug="web",
        channel="web",
        settings_json={},
        is_active=True,
    )
    requested_route = ChannelAgentRoute(
        id=uuid4(),
        channel="web",
        route_key="site-b",
        channel_connection_id=connection.id,
        agent_id=profile.id,
        is_active=True,
    )
    conversation = ChatConversation(
        id=uuid4(),
        agent_id=profile.id,
        principal_id=uuid4(),
        channel="web",
        external_thread_id=str(uuid4()),
        route_key="site-a",
        channel_route_id=uuid4(),
        transcript_consent=True,
    )
    inbound = ChatMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        client_message_id="client",
        role="user",
        content="same input",
        status="completed",
    )
    execution = ChatExecution(
        id=uuid4(),
        request_id=str(uuid4()),
        conversation_id=conversation.id,
        inbound_message_id=inbound.id,
        status="completed",
    )

    class ReplayDb:
        async def execute(self, _statement):
            return _Result(execution)

        async def get(self, model, _row_id):
            return inbound if model is ChatMessage else conversation

    monkeypatch.setattr(
        "app.services.chat_application.agent_runtime_resolver.resolve_route",
        AsyncMock(
            return_value=ResolvedAgentRoute(requested_route, connection, runtime)
        ),
    )
    request = InternalExecutionRequest(
        request_id=execution.request_id,
        session_id=conversation.external_thread_id,
        input="same input",
        consent=TranscriptConsent(granted=True, version="v1"),
        route_key="site-b",
    )
    with pytest.raises(AgentNotReady, match="another route"):
        await ChatApplicationService().execute_web(ReplayDb(), request)


@pytest.mark.asyncio
async def test_agent_loop_uses_resolved_runtime_limits(monkeypatch):
    profile = _profile()
    provider = ProviderConnection(
        id=uuid4(),
        name="P",
        slug="p",
        provider_type="openai",
        base_url="https://example.test/v1",
        settings_json={},
        encrypted_credentials="cipher",
        is_active=True,
    )
    config = _runtime(profile, provider)
    config.chat_model = "configured-model"
    config.temperature = 0.2
    config.max_output_tokens = 321
    config.max_iterations = 1
    config.max_tool_calls = 0
    config.loop_timeout_seconds = 10
    config.tool_timeout_seconds = 2
    config.tool_result_max_chars = 500
    runtime = ResolvedAgentRuntime(profile, config, provider, "request-scoped-key")
    assert "request-scoped-key" not in repr(runtime)
    monkeypatch.setattr(
        "app.services.agent_loop.knowledge_service.build_all_knowledge",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "app.services.agent_loop.rag_retrieval_service.search",
        AsyncMock(return_value=[]),
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    with patch("openai.AsyncOpenAI", return_value=client) as constructor:
        result = await run_agent_loop(
            user_message="hello",
            conversation_history=[],
            available_tools=[],
            tool_configs={},
            profile=profile,
            user_id=None,
            phone="test",
            request_id="runtime-test",
            db=object(),
            runtime=runtime,
        )
    assert result.response_text == "ok"
    constructor.assert_called_once_with(
        api_key="request-scoped-key", base_url="https://example.test/v1"
    )
    assert create.await_args.kwargs["model"] == "configured-model"
    assert create.await_args.kwargs["temperature"] == 0.2
    assert create.await_args.kwargs["max_tokens"] == 321


@pytest.mark.asyncio
async def test_promptlab_can_preview_an_explicit_inactive_agent(monkeypatch):
    inactive = _profile(active=False)
    monkeypatch.setattr(
        "app.routers.admin.promptlab.agent_profile_service.get_profile",
        AsyncMock(return_value=inactive),
    )
    monkeypatch.setattr(
        "app.routers.admin.promptlab.knowledge_service.build_all_knowledge",
        AsyncMock(return_value="agent-specific knowledge"),
    )
    result = await prompt_preview(
        PromptPreviewRequest(agent_id=str(inactive.id)),
        db=object(),
    )
    assert result.profile_name == inactive.name
    assert "agent-specific knowledge" in result.system_prompt


def test_release_migration_backfills_non_secret_runtime_only():
    path = (
        Path(__file__).parents[1]
        / "migrations_platform"
        / "versions"
        / "a31e4d8b27f0_agent_runtime_and_routes.py"
    )
    source = path.read_text()
    assert "INSERT INTO agent_runtime_configs" in source
    backfill = source[source.index("INSERT INTO agent_runtime_configs") :]
    assert "encrypted_credentials" not in backfill
    assert "WHERE p.slug = :default_slug" in backfill


@pytest.mark.asyncio
async def test_bootstrap_imports_legacy_secrets_once(tmp_path, monkeypatch):
    key_file = tmp_path / "master.key"
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(
        "app.services.credentials.settings.credential_encryption_key_file",
        str(key_file),
    )
    monkeypatch.setattr("app.bootstrap.settings.openai_api_key", "legacy-secret")
    monkeypatch.setattr("app.bootstrap.settings.whatsapp_token", "")
    monkeypatch.setattr(
        "app.bootstrap.settings.agent_web_route_key", "saltacode-landing"
    )
    db = _MemoryDb()
    profile = _profile()

    await bootstrap_operational_config(db, profile)
    await bootstrap_operational_config(db, profile)

    assert sum(isinstance(row, ProviderConnection) for row in db.rows) == 1
    assert sum(isinstance(row, AgentRuntimeConfig) for row in db.rows) == 1
    assert sum(isinstance(row, ChannelConnection) for row in db.rows) == 1
    assert sum(isinstance(row, ChannelAgentRoute) for row in db.rows) == 1
    provider = next(row for row in db.rows if isinstance(row, ProviderConnection))
    assert "legacy-secret" not in provider.encrypted_credentials
