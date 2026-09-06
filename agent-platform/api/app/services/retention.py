"""Enforce conversation retention without deleting active commercial evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.outbound import OutboundMessage
from app.models.platform import ChatConversation

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100
_TERMINAL_FOLLOW_UP_STATUSES = {"completed", "cancelled"}
_UNCERTAIN_OUTBOUND_STATUSES = {"dispatching", "delivery_unknown"}
_RETENTION_REVIEW_CODE = "retention_conversation_blocked"


async def purge_expired_conversations(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Delete eligible conversations in bounded batches, preserving follow-up facts."""

    reference = now or datetime.now(UTC)
    policies = (
        await db.execute(
            select(AgentProfile.id, AgentProfile.retention_days).where(
                AgentProfile.retention_days > 0
            )
        )
    ).all()

    deleted_count = 0
    for agent_id, retention_days in policies:
        cutoff = reference - timedelta(days=retention_days)
        cursor: uuid.UUID | None = None
        while True:
            statement = (
                select(ChatConversation)
                .where(
                    ChatConversation.agent_id == agent_id,
                    ChatConversation.updated_at < cutoff,
                )
                .order_by(ChatConversation.id)
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            if cursor is not None:
                statement = statement.where(ChatConversation.id > cursor)
            conversations = list((await db.execute(statement)).scalars().all())
            if not conversations:
                break
            cursor = conversations[-1].id
            for conversation in conversations:
                is_blocked = await _prepare_follow_up_retention(
                    db,
                    conversation=conversation,
                    occurred_at=reference,
                )
                if is_blocked:
                    continue
                deleted = await db.execute(
                    delete(ChatConversation).where(
                        ChatConversation.id == conversation.id
                    )
                )
                deleted_count += int(deleted.rowcount or 0)
            await db.commit()

    if not policies:
        await db.commit()
    return deleted_count


async def _prepare_follow_up_retention(
    db: AsyncSession,
    *,
    conversation: ChatConversation,
    occurred_at: datetime,
) -> bool:
    rows = (
        await db.execute(
            select(FollowUpTask, OutboundMessage.status)
            .outerjoin(
                OutboundMessage,
                OutboundMessage.id == FollowUpTask.outbound_message_id,
            )
            .where(FollowUpTask.conversation_id == conversation.id)
            .order_by(FollowUpTask.id)
            .with_for_update(of=FollowUpTask)
        )
    ).all()
    is_blocked = False
    for task, outbound_status in rows:
        _preserve_follow_up_evidence(task, conversation_id=conversation.id)
        if task.status not in _TERMINAL_FOLLOW_UP_STATUSES or _evidence_is_uncertain(
            task,
            outbound_status=outbound_status,
        ):
            is_blocked = True
            if task.status != "review_required":
                _move_to_retention_review(
                    db,
                    task=task,
                    routing_agent_id=conversation.agent_id,
                    occurred_at=occurred_at,
                )
            continue
        task.conversation_id = None
    return is_blocked


def _preserve_follow_up_evidence(
    task: FollowUpTask,
    *,
    conversation_id: uuid.UUID,
) -> None:
    task.source_conversation_id = task.source_conversation_id or conversation_id
    task.had_chat_message_evidence = (
        task.had_chat_message_evidence or task.chat_message_id is not None
    )
    task.had_outbound_message_evidence = (
        task.had_outbound_message_evidence or task.outbound_message_id is not None
    )


def _evidence_is_uncertain(
    task: FollowUpTask,
    *,
    outbound_status: str | None,
) -> bool:
    if outbound_status in _UNCERTAIN_OUTBOUND_STATUSES:
        return True
    if task.status != "completed":
        return False
    return task.executed_consent_record_id is None or not (
        task.had_chat_message_evidence
        or task.had_outbound_message_evidence
        or task.chat_message_id is not None
        or task.outbound_message_id is not None
    )


def _move_to_retention_review(
    db: AsyncSession,
    *,
    task: FollowUpTask,
    routing_agent_id: uuid.UUID,
    occurred_at: datetime,
) -> None:
    from_status = task.status
    task.status = "review_required"
    task.state_version += 1
    task.lease_owner = None
    task.lease_expires_at = None
    task.completed_at = None
    task.cancelled_at = None
    task.review_required_at = occurred_at
    task.last_safe_code = _RETENTION_REVIEW_CODE
    idempotency_key = f"retention-review:{task.state_version}"
    command_hash = hashlib.sha256(
        json.dumps(
            {
                "conversation_id": str(task.source_conversation_id),
                "from_status": from_status,
                "state_version": task.state_version,
                "task_id": str(task.id),
                "to_status": "review_required",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    db.add(
        FollowUpTaskEvent(
            id=uuid.uuid5(task.id, f"follow-up-event:{idempotency_key}"),
            task_id=task.id,
            opportunity_id=task.opportunity_id,
            event_type="transitioned",
            from_status=from_status,
            to_status="review_required",
            state_version=task.state_version,
            actor_type="system",
            actor_agent_id=None,
            actor_admin_id=None,
            actor_worker_id=None,
            routing_agent_id=routing_agent_id,
            automation_agent_id=task.assigned_agent_id,
            target_channel=task.target_channel,
            control_version=task.scheduled_control_version,
            automation_version=task.scheduled_automation_version,
            scheduled_policy_version=task.scheduled_policy_version,
            executed_policy_version=task.executed_policy_version,
            consent_record_id=task.consent_record_id,
            executed_consent_record_id=task.executed_consent_record_id,
            caused_by_consent_record_id=None,
            chat_message_id=task.chat_message_id,
            outbound_message_id=task.outbound_message_id,
            source_conversation_id=task.source_conversation_id,
            had_chat_message_evidence=task.had_chat_message_evidence,
            had_outbound_message_evidence=task.had_outbound_message_evidence,
            safe_code=_RETENTION_REVIEW_CODE,
            correlation_id=f"retention:{task.source_conversation_id}",
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            created_at=occurred_at,
        )
    )


async def run_retention_sweeper(
    session_factory: Callable[[], AsyncSession],
    interval_seconds: int,
) -> None:
    """Periodically enforce retention without coupling policy to transports."""

    interval = max(interval_seconds, 60)
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_factory() as db:
                deleted_count = await purge_expired_conversations(db)
            if deleted_count:
                logger.info(
                    "expired_conversations_deleted",
                    extra={"count": deleted_count},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("conversation_retention_sweep_failed")
