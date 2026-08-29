"""Focused coverage for agent-scoped history caching and summaries."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import AgentRuntimeConfig, ProviderConnection
from app.models.platform import ChatConversation, ChatMessage
from app.services.agent_runtime import ResolvedAgentRuntime
from app.services.chat_application import ChatApplicationService
from app.services.conversation_memory import ConversationMemoryService


class Result:
    def __init__(self, *, scalar_value=None, rows=None):
        self.scalar_value = scalar_value
        self.rows = rows or []

    def scalar(self):
        return self.scalar_value

    def scalars(self):
        return self

    def all(self):
        return self.rows


class SequenceDb:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        return self.results.pop(0)


class SummaryProvider:
    def __init__(self, result="updated summary"):
        self.result = result
        self.calls = []

    async def summarize(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.set_calls = []
        self.deleted = []

    async def get(self, key):
        return self.values.get(key)

    async def setex(self, key, ttl, value):
        self.values[key] = value
        self.set_calls.append((key, ttl, value))

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)


def runtime(*, summary_enabled=True, history_limit=2, trigger=2, ttl=300):
    profile = AgentProfile(
        id=uuid4(),
        name="Agent",
        slug="agent",
        is_active=True,
        is_public=True,
        retention_days=30,
        prompt_identity="identity",
        prompt_domain="domain",
        prompt_guardrails="guardrails",
        unauthorized_message="no",
        error_message="error",
    )
    provider = ProviderConnection(
        id=uuid4(),
        name="OpenAI",
        slug="openai",
        provider_type="openai",
        settings_json={},
        encrypted_credentials="cipher",
        is_active=True,
    )
    config = AgentRuntimeConfig(
        id=uuid4(),
        agent_id=profile.id,
        provider_connection_id=provider.id,
        chat_model="model",
        transcription_model="transcription",
        temperature=0.2,
        max_output_tokens=2000,
        max_iterations=3,
        max_tool_calls=3,
        loop_timeout_seconds=30,
        tool_timeout_seconds=10,
        tool_result_max_chars=1000,
        history_message_limit=history_limit,
        history_cache_ttl_seconds=ttl,
        summary_enabled=summary_enabled,
        summary_trigger_messages=trigger,
        summary_max_chars=4000,
        rag_enabled=False,
        rag_retrieval_top_k=4,
        rag_min_relevance_score=0.3,
        rag_vector_weight=0.7,
        rag_lexical_weight=0.3,
    )
    return ResolvedAgentRuntime(profile, config, provider, "secret")


def conversation():
    return ChatConversation(
        id=uuid4(),
        agent_id=uuid4(),
        principal_id=uuid4(),
        channel="web",
        external_thread_id="session",
        route_key="site",
        transcript_consent=True,
        attributes={},
    )


def messages(conversation_id, count):
    now = datetime.now(timezone.utc)
    return [
        ChatMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            client_message_id=f"message-{index}",
            role="user" if index % 2 == 0 else "assistant",
            content=f"content {index}",
            status="completed",
            created_at=now + timedelta(seconds=index),
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_summary_settings_control_agent_scoped_compaction():
    chat = conversation()
    pending = messages(chat.id, 2)
    provider = SummaryProvider()
    service = ConversationMemoryService(provider)
    db = SequenceDb(Result(scalar_value=4), Result(rows=pending))

    updated = await service.refresh_summary(
        db, conversation=chat, runtime=runtime(history_limit=2, trigger=2)
    )

    assert updated is True
    assert chat.summary == "updated summary"
    assert chat.attributes["summary_through"] == pending[-1].created_at.isoformat()
    assert provider.calls[0]["messages"] == pending
    assert provider.calls[0]["max_chars"] == 4000


@pytest.mark.asyncio
async def test_disabled_summary_does_not_query_storage_or_provider():
    chat = conversation()
    provider = SummaryProvider()
    db = SequenceDb()

    updated = await ConversationMemoryService(provider).refresh_summary(
        db, conversation=chat, runtime=runtime(summary_enabled=False)
    )

    assert updated is False
    assert db.calls == 0
    assert provider.calls == []


@pytest.mark.asyncio
async def test_history_cache_uses_runtime_ttl_and_is_invalidated():
    chat = conversation()
    stored = messages(chat.id, 2)
    db = SequenceDb(Result(rows=list(reversed(stored))))
    redis = FakeRedis()
    service = ChatApplicationService()

    history = await service._history(db, chat.id, 2, redis=redis, cache_ttl_seconds=45)
    cached = await service._history(
        SequenceDb(), chat.id, 2, redis=redis, cache_ttl_seconds=45
    )
    await service._invalidate_history(redis, chat.id, 2)

    assert (
        history
        == cached
        == [{"role": message.role, "content": message.content} for message in stored]
    )
    assert redis.set_calls[0][1] == 45
    assert redis.deleted == [service._history_cache_key(chat.id, 2)]


@pytest.mark.asyncio
async def test_invalid_history_cache_fails_open_to_durable_storage():
    chat = conversation()
    stored = messages(chat.id, 1)
    redis = FakeRedis()
    redis.values[ChatApplicationService._history_cache_key(chat.id, 1)] = (
        '[{"role":"system","content":"untrusted"}]'
    )

    history = await ChatApplicationService()._history(
        SequenceDb(Result(rows=stored)),
        chat.id,
        1,
        redis=redis,
        cache_ttl_seconds=45,
    )

    assert history == [{"role": "user", "content": "content 0"}]
