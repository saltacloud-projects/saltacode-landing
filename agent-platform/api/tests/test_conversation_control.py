"""Policy tests for serialized and agent-scoped conversation control."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.models.conversation_control import ConversationControlEvent
from app.models.platform import ChatMessage
from app.schemas.conversation_control import ConversationControlMode
from app.services.conversation_control import (
    AutomationBlockedError,
    ControlVersionConflictError,
    ConversationControlService,
    ConversationNotFoundError,
    InvalidControlTransitionError,
    OperatorControlRequiredError,
)
from app.services.conversation_events import ConversationEventVisibility


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _SequenceDb:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.flush_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    async def get(self, _model, _identifier):
        return None

    def add(self, model):
        self.added.append(model)

    async def flush(self):
        self.flush_count += 1


def _conversation(
    *,
    agent_id: UUID,
    mode: ConversationControlMode = ConversationControlMode.AUTOMATED,
    version: int = 0,
    assigned_admin_id: UUID | None = None,
    channel: str = "whatsapp",
):
    return SimpleNamespace(
        id=uuid4(),
        agent_id=agent_id,
        status="active",
        control_mode=mode.value,
        control_version=version,
        assigned_admin_id=assigned_admin_id,
        channel=channel,
        control_changed_at=datetime.now(UTC),
        control_reason=None,
    )


def _assert_agent_scope(statement, agent_id: UUID) -> None:
    assert "chat_conversations.agent_id" in str(statement).lower()
    assert agent_id in statement.compile().params.values()


@pytest.mark.asyncio
async def test_takeover_locks_conversation_and_creates_one_control_epoch():
    agent_id = uuid4()
    operator_id = uuid4()
    conversation = _conversation(agent_id=agent_id)
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()

    result = await service.transition(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=operator_id,
        target_mode=ConversationControlMode.HUMAN,
        expected_version=0,
        reason="Lead requested a person",
    )

    _assert_agent_scope(db.statements[0], agent_id)
    assert db.statements[0]._for_update_arg is not None
    assert result.control_mode == "human"
    assert result.control_version == 1
    assert result.assigned_admin_id == operator_id
    assert result.control_reason == "Lead requested a person"
    assert db.flush_count == 1
    event = db.added[0]
    assert isinstance(event, ConversationControlEvent)
    assert event.event_type == "taken_over"
    assert event.control_version == 1
    assert event.actor_admin_id == operator_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_mode", "target_mode", "current_owner", "expected_event"),
    [
        (
            ConversationControlMode.AUTOMATED,
            ConversationControlMode.PAUSED,
            False,
            "paused",
        ),
        (
            ConversationControlMode.AUTOMATED,
            ConversationControlMode.HUMAN,
            False,
            "taken_over",
        ),
        (
            ConversationControlMode.HUMAN,
            ConversationControlMode.HUMAN,
            True,
            "reassigned",
        ),
        (
            ConversationControlMode.PAUSED,
            ConversationControlMode.AUTOMATED,
            False,
            "resumed",
        ),
        (
            ConversationControlMode.AUTOMATED,
            ConversationControlMode.CLOSED,
            False,
            "closed",
        ),
    ],
)
async def test_web_control_transitions_publish_sanitized_public_state(
    monkeypatch,
    current_mode,
    target_mode,
    current_owner,
    expected_event,
):
    agent_id = uuid4()
    actor_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=current_mode,
        version=2,
        assigned_admin_id=uuid4() if current_owner else None,
        channel="web",
    )
    db = _SequenceDb(_Result(conversation))
    publish = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(
        "app.services.conversation_control.conversation_event_service.publish",
        publish,
    )

    result = await ConversationControlService().transition(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=actor_id,
        target_mode=target_mode,
        expected_version=2,
        reason="private operator reason",
    )

    assert db.added[0].event_type == expected_event
    assert publish.await_args.kwargs["event_type"] == "chat.control.changed"
    assert publish.await_args.kwargs["visibility"] == ConversationEventVisibility.PUBLIC
    assert publish.await_args.kwargs["payload"] == {
        "mode": target_mode.value,
        "status": result.status,
    }
    public_payload = publish.await_args.kwargs["payload"]
    assert "actor_admin_id" not in public_payload
    assert "assigned_admin_id" not in public_payload
    assert "reason" not in public_payload


@pytest.mark.asyncio
async def test_stale_transition_is_rejected_before_writing():
    agent_id = uuid4()
    conversation = _conversation(agent_id=agent_id, version=3)
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()

    with pytest.raises(ControlVersionConflictError) as exc:
        await service.transition(
            db,
            conversation_id=conversation.id,
            agent_id=agent_id,
            actor_admin_id=uuid4(),
            target_mode=ConversationControlMode.PAUSED,
            expected_version=2,
        )

    assert exc.value.actual == 3
    assert db.added == []
    assert db.flush_count == 0


@pytest.mark.asyncio
async def test_cross_agent_lookup_is_indistinguishable_from_missing_conversation():
    requested_agent_id = uuid4()
    db = _SequenceDb(_Result(None))
    service = ConversationControlService()

    with pytest.raises(ConversationNotFoundError):
        await service.get_snapshot(
            db,
            conversation_id=uuid4(),
            agent_id=requested_agent_id,
        )

    _assert_agent_scope(db.statements[0], requested_agent_id)


@pytest.mark.asyncio
async def test_closed_conversation_is_terminal():
    agent_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.CLOSED,
        version=4,
    )
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()

    with pytest.raises(InvalidControlTransitionError):
        await service.transition(
            db,
            conversation_id=conversation.id,
            agent_id=agent_id,
            actor_admin_id=uuid4(),
            target_mode=ConversationControlMode.AUTOMATED,
            expected_version=4,
        )


@pytest.mark.asyncio
async def test_closing_control_also_closes_the_operational_conversation():
    agent_id = uuid4()
    operator_id = uuid4()
    conversation = _conversation(agent_id=agent_id)
    conversation.status = "active"
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()

    result = await service.transition(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=operator_id,
        target_mode=ConversationControlMode.CLOSED,
        expected_version=0,
    )

    assert result.control_mode == "closed"
    assert result.status == "closed"


@pytest.mark.asyncio
async def test_reassignment_rejects_an_operator_without_management_permission():
    agent_id = uuid4()
    current_owner_id = uuid4()
    target_operator_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.HUMAN,
        version=3,
        assigned_admin_id=current_owner_id,
    )
    target_operator = SimpleNamespace(
        id=target_operator_id,
        role="conversation_viewer",
    )
    db = _SequenceDb(
        _Result(conversation),
        _Result(target_operator),
        _Result(["conversations.read"]),
    )
    service = ConversationControlService()

    with pytest.raises(
        InvalidControlTransitionError,
        match="cannot manage conversations",
    ):
        await service.transition(
            db,
            conversation_id=conversation.id,
            agent_id=agent_id,
            actor_admin_id=current_owner_id,
            target_mode=ConversationControlMode.HUMAN,
            expected_version=3,
            assigned_admin_id=target_operator_id,
        )

    assert conversation.control_version == 3
    assert db.added == []


@pytest.mark.asyncio
async def test_reassignment_accepts_an_active_conversation_operator():
    agent_id = uuid4()
    current_owner_id = uuid4()
    target_operator_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.HUMAN,
        version=3,
        assigned_admin_id=current_owner_id,
    )
    target_operator = SimpleNamespace(id=target_operator_id, role="operator")
    db = _SequenceDb(
        _Result(conversation),
        _Result(target_operator),
        _Result(["conversations.manage"]),
    )
    service = ConversationControlService()

    result = await service.transition(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=current_owner_id,
        target_mode=ConversationControlMode.HUMAN,
        expected_version=3,
        assigned_admin_id=target_operator_id,
    )

    assert result.control_version == 4
    assert result.assigned_admin_id == target_operator_id
    assert db.added[0].event_type == "reassigned"


@pytest.mark.asyncio
async def test_operator_message_requires_current_owner():
    agent_id = uuid4()
    owner_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.HUMAN,
        version=2,
        assigned_admin_id=owner_id,
    )
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()

    with pytest.raises(OperatorControlRequiredError):
        await service.record_operator_message(
            db,
            conversation_id=conversation.id,
            agent_id=agent_id,
            actor_admin_id=uuid4(),
            content="I can help with that.",
            expected_version=2,
            idempotency_key="manual-reply-1",
        )

    assert db.added == []


@pytest.mark.asyncio
async def test_operator_message_and_outbound_command_are_persisted_together(
    monkeypatch,
):
    agent_id = uuid4()
    operator_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.HUMAN,
        version=2,
        assigned_admin_id=operator_id,
    )
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()
    queued = SimpleNamespace(message=SimpleNamespace(status="queued"), duplicate=False)
    enqueue = AsyncMock(return_value=queued)
    monkeypatch.setattr(
        "app.services.conversation_control.outbound_delivery_service.enqueue",
        enqueue,
    )

    result, message, delivery = await service.record_operator_message(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=operator_id,
        content="I can help with that.",
        expected_version=2,
        idempotency_key="manual-reply-1",
    )

    assert result.control_version == 2
    assert isinstance(message, ChatMessage)
    assert message.status == "completed"
    assert message.metadata_json["origin"] == "operator"
    assert message.metadata_json["control_version"] == 2
    assert delivery.delivery_status == "queued"
    assert delivery.duplicate is False
    assert enqueue.await_args.kwargs["chat_message_id"] == message.id
    assert enqueue.await_args.kwargs["idempotency_key"] == "operator:manual-reply-1"
    assert not any(isinstance(item, ConversationControlEvent) for item in db.added)
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_web_operator_message_publishes_safe_public_event_without_outbox(
    monkeypatch,
):
    agent_id = uuid4()
    operator_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.HUMAN,
        version=2,
        assigned_admin_id=operator_id,
        channel="web",
    )
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()
    published_event = SimpleNamespace(id=uuid4())
    publish = AsyncMock(return_value=published_event)
    enqueue = AsyncMock()
    monkeypatch.setattr(
        "app.services.conversation_control.conversation_event_service.publish",
        publish,
    )
    monkeypatch.setattr(
        "app.services.conversation_control.outbound_delivery_service.enqueue",
        enqueue,
    )

    result, message, delivery = await service.record_operator_message(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=operator_id,
        content="I can help with that.",
        expected_version=2,
        idempotency_key="manual-web-reply-1",
    )

    assert result.control_version == 2
    assert delivery.delivery_status == "published"
    assert delivery.duplicate is False
    assert message.metadata_json["public_event_id"] == str(published_event.id)
    assert publish.await_args.kwargs["event_type"] == "chat.message.completed"
    assert publish.await_args.kwargs["payload"] == {
        "message_id": str(message.id),
        "content": "I can help with that.",
        "status": "completed",
        "actor": "human",
    }
    assert "actor_admin_id" not in publish.await_args.kwargs["payload"]
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_automation_guard_rejects_human_control():
    agent_id = uuid4()
    conversation = _conversation(
        agent_id=agent_id,
        mode=ConversationControlMode.HUMAN,
        assigned_admin_id=uuid4(),
    )
    db = _SequenceDb(_Result(conversation))
    service = ConversationControlService()

    with pytest.raises(AutomationBlockedError):
        await service.assert_automation_allowed(
            db,
            conversation_id=conversation.id,
            agent_id=agent_id,
            expected_version=0,
        )
