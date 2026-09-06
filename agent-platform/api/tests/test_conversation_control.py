"""Policy tests for serialized and agent-scoped conversation control."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
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
):
    return SimpleNamespace(
        id=uuid4(),
        agent_id=agent_id,
        control_mode=mode.value,
        control_version=version,
        assigned_admin_id=assigned_admin_id,
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
        )

    assert db.added == []


@pytest.mark.asyncio
async def test_operator_message_is_persisted_without_claiming_external_delivery():
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

    result, message = await service.record_operator_message(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        actor_admin_id=operator_id,
        content="I can help with that.",
        expected_version=2,
    )

    assert result.control_version == 2
    assert isinstance(message, ChatMessage)
    assert message.status == "pending_delivery"
    assert message.metadata_json["origin"] == "operator"
    assert message.metadata_json["control_version"] == 2
    assert message.metadata_json["delivery"] == "not_attempted"
    assert not any(isinstance(item, ConversationControlEvent) for item in db.added)
    assert db.flush_count == 1


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
