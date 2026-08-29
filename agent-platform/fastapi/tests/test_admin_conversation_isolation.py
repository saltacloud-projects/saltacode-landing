"""Agent ownership regression tests for admin conversation surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException

from app.routers.admin.conversations import (
    delete_conversation,
    get_conversation_history,
    list_conversations,
)
from app.routers.admin.conversations import (
    router as conversations_router,
)
from app.routers.admin.promptlab import (
    router as promptlab_router,
)
from app.routers.admin.promptlab import (
    search_conversations,
)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, rows=None, scalar=None, scalars=None, rowcount=0):
        self._rows = rows or []
        self._scalar = scalar
        self._scalars = scalars or []
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _Scalars(self._scalars)


class _SequenceDb:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def _assert_agent_filter(statement, agent_id: UUID) -> None:
    sql = str(statement).lower()
    assert "chat_conversations.agent_id" in sql
    assert agent_id in statement.compile().params.values()


def _conversation(agent_id: UUID, label: str):
    return SimpleNamespace(
        id=uuid4(),
        agent_id=agent_id,
        principal_id=uuid4(),
        channel="web",
        route_key=f"route-{label}",
        external_thread_id=f"session-{label}",
        status="active",
        transcript_consent=True,
        consent_version="v1",
        updated_at=datetime.now(timezone.utc),
    )


def _message(conversation_id: UUID, label: str):
    return SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content=f"message {label}",
        status="completed",
        tool_names=[],
        metadata_json={},
        created_at=datetime.now(timezone.utc),
    )


def test_all_admin_conversation_contracts_require_agent_id():
    app = FastAPI()
    app.include_router(conversations_router, prefix="/api/admin/conversations")
    app.include_router(promptlab_router, prefix="/api/admin/promptlab")
    expected = {
        ("/api/admin/conversations/", "GET"),
        ("/api/admin/conversations/{conversation_id}/messages", "GET"),
        ("/api/admin/conversations/{conversation_id}", "DELETE"),
        ("/api/admin/promptlab/search-conversations", "GET"),
    }
    schema = app.openapi()

    for path, method in expected:
        operation = schema["paths"][path][method.lower()]
        agent_param = next(
            item
            for item in operation["parameters"]
            if item["name"] == "agent_id" and item["in"] == "query"
        )
        assert agent_param["required"] is True


@pytest.mark.asyncio
async def test_list_is_agent_scoped_and_returns_route_identity():
    agent_a, agent_b = uuid4(), uuid4()
    conversation_a = _conversation(agent_a, "a")
    conversation_b = _conversation(agent_b, "b")
    now = datetime.now(timezone.utc)
    db_a = _SequenceDb(_Result(rows=[(conversation_a, "agent-a", "Alice", 2, now)]))
    db_b = _SequenceDb(_Result(rows=[(conversation_b, "agent-b", "Bob", 1, now)]))

    result_a = await list_conversations(agent_a, None, 100, 0, db_a)
    result_b = await list_conversations(agent_b, None, 100, 0, db_b)

    _assert_agent_filter(db_a.statements[0], agent_a)
    _assert_agent_filter(db_b.statements[0], agent_b)
    assert [item.agent_slug for item in result_a] == ["agent-a"]
    assert [item.agent_slug for item in result_b] == ["agent-b"]
    assert result_a[0].route_key == "route-a"
    assert result_a[0].external_thread_id == "session-a"


@pytest.mark.asyncio
async def test_messages_return_404_for_another_agent():
    agent_a, agent_b = uuid4(), uuid4()
    conversation = _conversation(agent_a, "a")
    message = _message(conversation.id, "a")
    db_a = _SequenceDb(_Result(scalar=conversation.id), _Result(scalars=[message]))
    db_b = _SequenceDb(_Result(scalar=None))

    result = await get_conversation_history(str(conversation.id), agent_a, 100, 0, db_a)
    with pytest.raises(HTTPException) as exc:
        await get_conversation_history(str(conversation.id), agent_b, 100, 0, db_b)

    _assert_agent_filter(db_a.statements[0], agent_a)
    _assert_agent_filter(db_b.statements[0], agent_b)
    assert [item.content for item in result] == ["message a"]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_returns_404_for_another_agent():
    agent_a, agent_b = uuid4(), uuid4()
    conversation_id = uuid4()
    db_a = _SequenceDb(_Result(rowcount=1))
    db_b = _SequenceDb(_Result(rowcount=0))

    assert await delete_conversation(str(conversation_id), agent_a, db_a) is None
    with pytest.raises(HTTPException) as exc:
        await delete_conversation(str(conversation_id), agent_b, db_b)

    _assert_agent_filter(db_a.statements[0], agent_a)
    _assert_agent_filter(db_b.statements[0], agent_b)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_promptlab_search_is_agent_scoped_and_uses_neutral_models():
    agent_a, agent_b = uuid4(), uuid4()
    conversation_a = _conversation(agent_a, "a")
    conversation_b = _conversation(agent_b, "b")
    message_a = _message(conversation_a.id, "a")
    message_b = _message(conversation_b.id, "b")
    db_a = _SequenceDb(_Result(rows=[(message_a, conversation_a, "Alice")]))
    db_b = _SequenceDb(_Result(rows=[(message_b, conversation_b, "Bob")]))

    result_a = await search_conversations(agent_a, "message", None, 50, db_a)
    result_b = await search_conversations(agent_b, "message", None, 50, db_b)

    _assert_agent_filter(db_a.statements[0], agent_a)
    _assert_agent_filter(db_b.statements[0], agent_b)
    sql = str(db_a.statements[0]).lower()
    assert "chat_messages" in sql
    assert "principals" in sql
    assert "conversation_messages" not in sql
    assert [item.conversation_id for item in result_a] == [str(conversation_a.id)]
    assert [item.conversation_id for item in result_b] == [str(conversation_b.id)]
    assert result_a[0].external_thread_id == "session-a"
    assert result_a[0].display_name == "Alice"
