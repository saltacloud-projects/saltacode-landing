"""Schema and pure policy coverage for the transactional outbound queue."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryEvent,
    OutboundMessage,
)
from app.models.platform import ChatConversation
from app.services.outbound_delivery import (
    InvalidOutboundCommandError,
    OutboundDeliveryService,
    OutboundFenceViolationError,
    OutboundKind,
    OutboundSenderType,
)


def _conversation(*, mode: str = "automated", version: int = 0):
    return ChatConversation(
        id=uuid4(),
        agent_id=uuid4(),
        principal_id=uuid4(),
        channel="whatsapp",
        route_key="test-route",
        external_thread_id="test-subject",
        channel_route_id=uuid4(),
        control_mode=mode,
        control_version=version,
        assigned_admin_id=uuid4() if mode == "human" else None,
        next_outbound_sequence=1,
    )


def test_outbound_metadata_enforces_queue_and_append_only_contracts():
    conversation_constraints = {
        constraint.name for constraint in ChatConversation.__table__.constraints
    }
    message_constraints = {
        constraint.name for constraint in OutboundMessage.__table__.constraints
    }
    attempt_constraints = {
        constraint.name for constraint in OutboundAttempt.__table__.constraints
    }

    assert ChatConversation.__table__.c.next_outbound_sequence.default.arg == 1
    assert "ck_chat_conversation_next_outbound_sequence" in conversation_constraints
    assert "uq_outbound_message_conversation_sequence" in message_constraints
    assert "uq_outbound_message_conversation_idempotency" in message_constraints
    assert "uq_outbound_message_route_provider_id" in message_constraints
    assert "ck_outbound_message_sender_actor" in message_constraints
    assert "ck_outbound_message_kind" in message_constraints
    assert "ck_outbound_message_payload_shape" in message_constraints
    assert OutboundMessage.__table__.c.destination.nullable is False
    assert OutboundMessage.__table__.c.chat_message_id.nullable is True
    assert (
        next(iter(OutboundMessage.__table__.c.chat_message_id.foreign_keys)).ondelete
        == "SET NULL"
    )
    assert "uq_outbound_attempt_message_number" in attempt_constraints
    assert "updated_at" not in OutboundAttempt.__table__.columns
    assert "updated_at" not in OutboundDeliveryEvent.__table__.columns
    assert set(OutboundDeliveryEvent.__table__.columns.keys()) == {
        "id",
        "outbound_message_id",
        "attempt_id",
        "event_type",
        "from_status",
        "to_status",
        "actor_type",
        "actor_id",
        "safe_code",
        "created_at",
    }


def test_sender_fence_requires_current_mode_version_and_operator_owner():
    service = OutboundDeliveryService()
    automated = _conversation()
    service._assert_sender_fence(
        automated,
        sender_type=OutboundSenderType.AUTOMATION,
        sender_admin_id=None,
        control_version=0,
    )
    service._assert_sender_fence(
        automated,
        sender_type=OutboundSenderType.SYSTEM,
        sender_admin_id=None,
        control_version=0,
    )
    with pytest.raises(OutboundFenceViolationError, match="epoch"):
        service._assert_sender_fence(
            automated,
            sender_type=OutboundSenderType.AUTOMATION,
            sender_admin_id=None,
            control_version=1,
        )

    human = _conversation(mode="human", version=3)
    service._assert_sender_fence(
        human,
        sender_type=OutboundSenderType.OPERATOR,
        sender_admin_id=human.assigned_admin_id,
        control_version=3,
    )
    with pytest.raises(OutboundFenceViolationError, match="does not own"):
        service._assert_sender_fence(
            human,
            sender_type=OutboundSenderType.OPERATOR,
            sender_admin_id=uuid4(),
            control_version=3,
        )
    with pytest.raises(OutboundFenceViolationError, match="blocked"):
        service._assert_sender_fence(
            human,
            sender_type=OutboundSenderType.SYSTEM,
            sender_admin_id=None,
            control_version=3,
        )


def test_payload_hash_is_deterministic_and_does_not_expose_payload_body():
    service = OutboundDeliveryService()
    conversation = _conversation()
    chat_message_id = uuid4()
    payload = {"text": "private message content"}
    first = service._command_hash(
        conversation=conversation,
        destination=conversation.external_thread_id,
        chat_message_id=chat_message_id,
        kind=OutboundKind.TEXT,
        payload=payload,
        sender_type=OutboundSenderType.AUTOMATION,
        sender_admin_id=None,
        control_version=0,
    )
    second = service._command_hash(
        conversation=conversation,
        destination=conversation.external_thread_id,
        chat_message_id=chat_message_id,
        kind=OutboundKind.TEXT,
        payload=payload,
        sender_type=OutboundSenderType.AUTOMATION,
        sender_admin_id=None,
        control_version=0,
    )

    assert first == second
    assert len(first) == 64
    assert "private message content" not in first


def test_payload_hash_changes_for_command_content_actor_and_control_epoch():
    service = OutboundDeliveryService()
    conversation = _conversation()
    chat_message_id = uuid4()
    base = {
        "conversation": conversation,
        "destination": conversation.external_thread_id,
        "chat_message_id": chat_message_id,
        "kind": OutboundKind.TEXT,
        "payload": {"text": "Answer"},
        "sender_type": OutboundSenderType.AUTOMATION,
        "sender_admin_id": None,
        "control_version": 0,
    }

    hashes = {
        service._command_hash(**base),
        service._command_hash(**{**base, "payload": {"text": "Changed answer"}}),
        service._command_hash(
            **{
                **base,
                "kind": OutboundKind.TEMPLATE,
                "payload": {"template_key": "follow_up", "language": "es_AR"},
            }
        ),
        service._command_hash(
            **{
                **base,
                "sender_type": OutboundSenderType.OPERATOR,
                "sender_admin_id": uuid4(),
            }
        ),
        service._command_hash(**{**base, "control_version": 1}),
    }

    assert len(hashes) == 5


def test_payload_validation_freezes_only_neutral_dispatch_data():
    service = OutboundDeliveryService()
    source = {
        "storage_key": "blobs/ab/proposal.pdf",
        "name": "proposal.pdf",
        "mime": "application/pdf",
        "caption": "Proposal",
    }
    normalized = service._normalize_payload(
        kind=OutboundKind.DOCUMENT,
        payload=source,
    )
    source["caption"] = "mutated"

    assert normalized["caption"] == "Proposal"
    with pytest.raises(InvalidOutboundCommandError, match="payload fields"):
        service._normalize_payload(
            kind=OutboundKind.DOCUMENT,
            payload={**normalized, "file_bytes": "base64-data"},
        )
    with pytest.raises(InvalidOutboundCommandError, match="image mime"):
        service._normalize_payload(
            kind=OutboundKind.IMAGE,
            payload={
                "storage_key": "blobs/ab/proposal.pdf",
                "name": "proposal.pdf",
                "mime": "application/pdf",
            },
        )


@pytest.mark.asyncio
async def test_dispatch_outcome_rejects_provider_bodies_as_safe_codes():
    with pytest.raises(InvalidOutboundCommandError, match="safe result code"):
        await OutboundDeliveryService().record_dispatch_outcome(
            object(),
            outbound_message_id=uuid4(),
            attempt_id=uuid4(),
            worker_id="worker-1",
            outcome="failed",
            safe_code="HTTP 500: provider response body",
        )

    with pytest.raises(
        InvalidOutboundCommandError,
        match="requires a provider message id",
    ):
        await OutboundDeliveryService().record_dispatch_outcome(
            object(),
            outbound_message_id=uuid4(),
            attempt_id=uuid4(),
            worker_id="worker-1",
            outcome="accepted",
            provider_message_id="   ",
        )
