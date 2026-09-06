"""Policy tests for versioned conversation automation assignments."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentClosedError,
    ConversationAutomationAssignmentIdempotencyError,
    ConversationAutomationAssignmentService,
    ConversationAutomationAssignmentValidationError,
    ConversationAutomationAssignmentVersionConflictError,
)


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


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
    routing_agent_id: UUID,
    automation_agent_id: UUID,
    automation_version: int = 0,
    status: str = "active",
    control_mode: str = "automated",
):
    return SimpleNamespace(
        id=uuid4(),
        agent_id=routing_agent_id,
        automation_agent_id=automation_agent_id,
        automation_version=automation_version,
        status=status,
        control_mode=control_mode,
    )


def _command_kwargs(conversation, *, target_agent_id: UUID) -> dict[str, object]:
    return {
        "conversation_id": conversation.id,
        "routing_agent_id": conversation.agent_id,
        "target_agent_id": target_agent_id,
        "expected_automation_version": conversation.automation_version,
        "actor_agent_id": conversation.agent_id,
        "actor_admin_id": None,
        "trigger": "quote_requested",
        "opportunity_id": None,
        "correlation_id": "assignment-correlation",
        "idempotency_key": "assignment-command",
        "reason": "Commercial specialist requested",
    }


@pytest.mark.asyncio
async def test_assignment_locks_routing_scope_and_advances_one_epoch() -> None:
    routing_agent_id = uuid4()
    target_agent_id = uuid4()
    conversation = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
    )
    db = _SequenceDb(
        _Result(scalar=None),
        _Result(scalar=conversation),
        _Result(scalar=None),
        _Result(rows=[routing_agent_id, target_agent_id]),
    )

    result = await ConversationAutomationAssignmentService().assign(
        db,
        **_command_kwargs(conversation, target_agent_id=target_agent_id),
    )

    lock = db.statements[1]
    assert lock._for_update_arg is not None
    assert "chat_conversations.agent_id" in str(lock).lower()
    assert routing_agent_id in lock.compile().params.values()
    assert conversation.agent_id == routing_agent_id
    assert conversation.automation_agent_id == target_agent_id
    assert conversation.automation_version == 1
    assert result.applied is True
    assert result.duplicate is False
    assert db.flush_count == 1
    assert isinstance(result.event, ConversationAutomationAssignmentEvent)
    assert result.event.routing_agent_id == routing_agent_id
    assert result.event.from_automation_agent_id == routing_agent_id
    assert result.event.to_automation_agent_id == target_agent_id
    assert result.event.automation_version == 1


@pytest.mark.asyncio
async def test_unchanged_assignment_is_audited_without_advancing_version() -> None:
    routing_agent_id = uuid4()
    conversation = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
        automation_version=3,
    )
    db = _SequenceDb(
        _Result(scalar=None),
        _Result(scalar=conversation),
        _Result(scalar=None),
        _Result(rows=[routing_agent_id]),
    )

    result = await ConversationAutomationAssignmentService().assign(
        db,
        **_command_kwargs(conversation, target_agent_id=routing_agent_id),
    )

    assert result.applied is False
    assert result.duplicate is False
    assert result.event.applied is False
    assert result.event.automation_version == 3
    assert conversation.automation_version == 3


@pytest.mark.asyncio
async def test_duplicate_is_resolved_before_loading_mutable_conversation() -> None:
    routing_agent_id = uuid4()
    target_agent_id = uuid4()
    conversation = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
    )
    first_db = _SequenceDb(
        _Result(scalar=None),
        _Result(scalar=conversation),
        _Result(scalar=None),
        _Result(rows=[routing_agent_id, target_agent_id]),
    )
    service = ConversationAutomationAssignmentService()
    first = await service.assign(
        first_db,
        **_command_kwargs(conversation, target_agent_id=target_agent_id),
    )
    replay_db = _SequenceDb(_Result(scalar=first.event))

    replay = await service.assign(
        replay_db,
        **{
            **_command_kwargs(conversation, target_agent_id=target_agent_id),
            "expected_automation_version": 0,
        },
    )

    assert replay.duplicate is True
    assert replay.applied is False
    assert replay.event is first.event
    assert len(replay_db.statements) == 1
    assert replay_db.flush_count == 0


@pytest.mark.asyncio
async def test_reused_key_with_changed_command_is_rejected() -> None:
    routing_agent_id = uuid4()
    target_agent_id = uuid4()
    conversation = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
    )
    first_db = _SequenceDb(
        _Result(scalar=None),
        _Result(scalar=conversation),
        _Result(scalar=None),
        _Result(rows=[routing_agent_id, target_agent_id]),
    )
    service = ConversationAutomationAssignmentService()
    first = await service.assign(
        first_db,
        **_command_kwargs(conversation, target_agent_id=target_agent_id),
    )

    with pytest.raises(ConversationAutomationAssignmentIdempotencyError):
        await service.assign(
            _SequenceDb(_Result(scalar=first.event)),
            **{
                **_command_kwargs(conversation, target_agent_id=target_agent_id),
                "expected_automation_version": 0,
                "reason": "A different command",
            },
        )


@pytest.mark.asyncio
async def test_stale_closed_and_unlinked_opportunity_commands_fail_closed() -> None:
    routing_agent_id = uuid4()
    target_agent_id = uuid4()
    stale = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
        automation_version=4,
    )
    kwargs = _command_kwargs(stale, target_agent_id=target_agent_id)
    with pytest.raises(ConversationAutomationAssignmentVersionConflictError) as error:
        await ConversationAutomationAssignmentService().assign(
            _SequenceDb(
                _Result(scalar=None),
                _Result(scalar=stale),
                _Result(scalar=None),
                _Result(rows=[routing_agent_id, target_agent_id]),
            ),
            **{**kwargs, "expected_automation_version": 3},
        )
    assert error.value.actual == 4

    closed = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
        status="closed",
        control_mode="closed",
    )
    with pytest.raises(ConversationAutomationAssignmentClosedError):
        await ConversationAutomationAssignmentService().assign(
            _SequenceDb(
                _Result(scalar=None),
                _Result(scalar=closed),
                _Result(scalar=None),
            ),
            **_command_kwargs(closed, target_agent_id=target_agent_id),
        )

    active = _conversation(
        routing_agent_id=routing_agent_id,
        automation_agent_id=routing_agent_id,
    )
    with pytest.raises(ConversationAutomationAssignmentValidationError):
        await ConversationAutomationAssignmentService().assign(
            _SequenceDb(
                _Result(scalar=None),
                _Result(scalar=active),
                _Result(scalar=None),
                _Result(rows=[routing_agent_id, target_agent_id]),
                _Result(scalar=None),
            ),
            **{
                **_command_kwargs(active, target_agent_id=target_agent_id),
                "opportunity_id": uuid4(),
            },
        )


@pytest.mark.asyncio
async def test_assignment_requires_exactly_one_actor() -> None:
    conversation = _conversation(
        routing_agent_id=uuid4(),
        automation_agent_id=uuid4(),
    )
    service = ConversationAutomationAssignmentService()

    for actor_agent_id, actor_admin_id in ((None, None), (uuid4(), uuid4())):
        with pytest.raises(ConversationAutomationAssignmentValidationError):
            await service.assign(
                _SequenceDb(),
                **{
                    **_command_kwargs(
                        conversation,
                        target_agent_id=uuid4(),
                    ),
                    "actor_agent_id": actor_agent_id,
                    "actor_admin_id": actor_admin_id,
                },
            )
