"""Conversation retention policy tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.retention import (
    _evidence_is_uncertain,
    _prepare_follow_up_retention,
    purge_expired_conversations,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _NoPolicySession:
    def __init__(self):
        self.commits = 0

    async def execute(self, _statement):
        return _Result([])

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_purge_commits_when_no_profiles_have_retention() -> None:
    db = _NoPolicySession()

    assert await purge_expired_conversations(db) == 0
    assert db.commits == 1


def test_completed_follow_up_without_durable_output_is_uncertain() -> None:
    task = SimpleNamespace(
        status="completed",
        executed_consent_record_id=uuid4(),
        had_chat_message_evidence=False,
        had_outbound_message_evidence=False,
        chat_message_id=None,
        outbound_message_id=None,
    )

    assert _evidence_is_uncertain(task, outbound_status=None) is True


def test_delivery_unknown_is_uncertain_even_for_cancelled_work() -> None:
    task = SimpleNamespace(
        status="cancelled",
        executed_consent_record_id=None,
        had_chat_message_evidence=False,
        had_outbound_message_evidence=True,
        chat_message_id=None,
        outbound_message_id=None,
    )

    assert _evidence_is_uncertain(task, outbound_status="delivery_unknown") is True


@pytest.mark.asyncio
async def test_active_follow_up_blocks_retention_and_moves_to_review() -> None:
    conversation_id = uuid4()
    task = SimpleNamespace(
        id=uuid4(),
        opportunity_id=uuid4(),
        conversation_id=conversation_id,
        source_conversation_id=None,
        status="scheduled",
        state_version=0,
        lease_owner=None,
        lease_expires_at=None,
        completed_at=None,
        cancelled_at=None,
        review_required_at=None,
        last_safe_code=None,
        assigned_agent_id=uuid4(),
        target_channel="whatsapp",
        scheduled_control_version=0,
        scheduled_automation_version=0,
        scheduled_policy_version=1,
        executed_policy_version=None,
        consent_record_id=uuid4(),
        executed_consent_record_id=None,
        chat_message_id=None,
        outbound_message_id=None,
        had_chat_message_evidence=False,
        had_outbound_message_evidence=False,
    )
    result = _Result([(task, None)])
    db = SimpleNamespace(execute=AsyncMock(return_value=result), add=lambda _row: None)
    conversation = SimpleNamespace(id=conversation_id, agent_id=uuid4())

    blocked = await _prepare_follow_up_retention(
        db,
        conversation=conversation,
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
    )

    assert blocked is True
    assert task.status == "review_required"
    assert task.source_conversation_id == conversation_id
    assert task.conversation_id == conversation_id
    assert task.last_safe_code == "retention_conversation_blocked"
