"""Unit contracts for resumable conversation events and web executions."""

import math

import pytest

from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution
from app.services.conversation_events import (
    ConversationEventService,
    InvalidConversationEventError,
)
from app.services.web_execution_queue import WebExecutionQueueService


def test_conversation_event_is_append_only_and_execution_metadata_is_durable():
    conversation_columns = ChatConversation.__table__.columns
    event_columns = ConversationEvent.__table__.columns
    execution_columns = ChatExecution.__table__.columns
    execution_constraints = {
        constraint.name for constraint in ChatExecution.__table__.constraints
    }

    assert conversation_columns.next_event_sequence.default.arg == 1
    assert "updated_at" not in event_columns
    assert execution_columns.status.default.arg == "queued"
    assert execution_columns.attempt_count.default.arg == 0
    assert execution_columns.automation_agent_id.nullable is False
    assert execution_columns.automation_version.default.arg == 0
    assert execution_columns.available_at.nullable is False
    assert "ck_chat_execution_automation_version" in execution_constraints
    assert "ck_chat_execution_status" in execution_constraints
    assert "ck_chat_execution_lease_pair" in execution_constraints
    assert "ck_chat_execution_lease_owner" in execution_constraints
    assert "uq_chat_execution_conversation_client_message" in execution_constraints


def test_event_payload_is_canonical_json_with_bounded_depth_and_size():
    service = ConversationEventService()

    assert service._normalize_payload({"z": 1, "a": [True, None]}) == {
        "a": [True, None],
        "z": 1,
    }
    with pytest.raises(InvalidConversationEventError):
        service._normalize_payload({"value": math.nan})
    with pytest.raises(InvalidConversationEventError):
        service._normalize_payload(
            {"level": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": 1}}}}}}}}}
        )
    with pytest.raises(InvalidConversationEventError):
        service._normalize_payload({"content": "x" * 33_000})


def test_web_input_hash_uses_semantic_input_not_delivery_metadata():
    service = WebExecutionQueueService()

    first = service._input_hash(content="Hello", locale="es-AR")
    duplicate = service._input_hash(content="Hello", locale="es-AR")
    changed = service._input_hash(content="Hello", locale="en-US")

    assert duplicate == first
    assert changed != first
