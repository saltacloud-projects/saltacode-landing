"""Durable PostgreSQL queue for resumable web-chat executions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatExecution, ChatMessage
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
)


class WebExecutionQueueError(Exception):
    """Base failure for durable web-execution operations."""


class WebExecutionConversationNotFoundError(WebExecutionQueueError):
    """The conversation is absent from the requested agent scope."""


class WebExecutionIdempotencyConflictError(WebExecutionQueueError):
    """A client message identifier was reused with different input."""


class WebExecutionAutomationBlockedError(WebExecutionQueueError):
    """Automation cannot accept work in the current ownership epoch."""


class InvalidWebExecutionCommandError(WebExecutionQueueError):
    """The requested queue operation violates its public contract."""


class WebExecutionClaimOwnershipError(WebExecutionQueueError):
    """The worker no longer owns the running execution lease."""


class WebExecutionOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EnqueuedWebExecution:
    execution: ChatExecution
    inbound_message: ChatMessage
    accepted_event: ConversationEvent
    duplicate: bool


@dataclass(frozen=True)
class ClaimedWebExecution:
    execution: ChatExecution
    inbound_message: ChatMessage


@dataclass(frozen=True)
class RecordedWebExecutionOutcome:
    execution: ChatExecution
    published: bool


class WebExecutionQueueService:
    """Persist, claim, and fence web work without in-process background tasks."""

    _blocking_statuses = ("queued", "running")
    _safe_code_pattern = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")

    def __init__(self, *, events: ConversationEventService | None = None) -> None:
        self._events = events or ConversationEventService()

    async def enqueue(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        client_message_id: str,
        content: str,
        locale: str,
        available_at: datetime | None = None,
    ) -> EnqueuedWebExecution:
        """Create an idempotent inbound message and job in the caller transaction."""
        normalized_client_id = client_message_id.strip()
        normalized_locale = locale.strip()
        if not normalized_client_id or len(normalized_client_id) > 255:
            raise InvalidWebExecutionCommandError("invalid client message id")
        if not content.strip() or len(content) > 16_000:
            raise InvalidWebExecutionCommandError("invalid web message content")
        if not normalized_locale or len(normalized_locale) > 35:
            raise InvalidWebExecutionCommandError("invalid locale")
        enqueue_at = available_at or datetime.now(timezone.utc)
        input_hash = self._input_hash(content=content, locale=normalized_locale)

        conversation = await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=True,
        )
        if conversation.channel != "web":
            raise InvalidWebExecutionCommandError(
                "web execution requires a web conversation"
            )

        existing = (
            (
                await db.execute(
                    select(ChatExecution).where(
                        ChatExecution.conversation_id == conversation.id,
                        ChatExecution.client_message_id == normalized_client_id,
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            if existing.input_hash != input_hash:
                raise WebExecutionIdempotencyConflictError(
                    "client message id belongs to different input"
                )
            inbound = await db.get(ChatMessage, existing.inbound_message_id)
            if inbound is None:
                raise WebExecutionQueueError("stored execution has no inbound message")
            accepted_event = (
                (
                    await db.execute(
                        select(ConversationEvent).where(
                            ConversationEvent.conversation_id == conversation.id,
                            ConversationEvent.sequence == existing.queue_sequence,
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if accepted_event is None:
                raise WebExecutionQueueError("stored execution has no accepted event")
            return EnqueuedWebExecution(
                execution=existing,
                inbound_message=inbound,
                accepted_event=accepted_event,
                duplicate=True,
            )

        self._assert_automation(conversation, expected_version=None)
        inbound_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        accepted_event = await self._events.publish(
            db,
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            event_type="chat.message.accepted",
            visibility=ConversationEventVisibility.PUBLIC,
            payload={
                "client_message_id": normalized_client_id,
                "execution_id": str(execution_id),
                "message_id": str(inbound_id),
                "status": "accepted",
            },
        )
        inbound = ChatMessage(
            id=inbound_id,
            conversation_id=conversation.id,
            client_message_id=normalized_client_id,
            role="user",
            content=content,
            status="accepted",
            metadata_json={"locale": normalized_locale},
        )
        execution = ChatExecution(
            id=execution_id,
            request_id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            inbound_message_id=inbound.id,
            status="queued",
            control_version=conversation.control_version,
            client_message_id=normalized_client_id,
            input_hash=input_hash,
            queue_sequence=accepted_event.sequence,
            attempt_count=0,
            available_at=enqueue_at,
        )
        db.add(inbound)
        await db.flush()
        db.add(execution)
        await db.flush()
        return EnqueuedWebExecution(
            execution=execution,
            inbound_message=inbound,
            accepted_event=accepted_event,
            duplicate=False,
        )

    async def claim_next(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> ClaimedWebExecution | None:
        """Claim one FIFO-eligible job while other conversations progress."""
        normalized_worker = worker_id.strip()
        if not normalized_worker or len(normalized_worker) > 120:
            raise InvalidWebExecutionCommandError("invalid worker id")
        if lease_duration <= timedelta(0):
            raise InvalidWebExecutionCommandError("lease duration must be positive")
        claimed_at = now or datetime.now(timezone.utc)
        await self.recover_stale_leases(db, now=claimed_at)

        while True:
            execution = (
                (
                    await db.execute(
                        self._eligible_statement(claimed_at).with_for_update(
                            skip_locked=True
                        )
                    )
                )
                .scalars()
                .first()
            )
            if execution is None:
                return None
            conversation = await self._get_execution_conversation(
                db,
                conversation_id=execution.conversation_id,
            )
            try:
                self._assert_automation(
                    conversation,
                    expected_version=execution.control_version,
                )
            except WebExecutionAutomationBlockedError:
                execution.status = "cancelled"
                execution.error_code = "conversation_control_changed"
                await self._events.publish(
                    db,
                    conversation_id=conversation.id,
                    agent_id=conversation.agent_id,
                    event_type="chat.execution.changed",
                    visibility=ConversationEventVisibility.PUBLIC,
                    payload={
                        "execution_id": str(execution.id),
                        "status": "cancelled",
                    },
                )
                await db.flush()
                continue

            execution.status = "running"
            execution.attempt_count += 1
            execution.lease_owner = normalized_worker
            execution.lease_expires_at = claimed_at + lease_duration
            await self._events.publish(
                db,
                conversation_id=conversation.id,
                agent_id=conversation.agent_id,
                event_type="chat.execution.changed",
                visibility=ConversationEventVisibility.PUBLIC,
                payload={
                    "execution_id": str(execution.id),
                    "status": "running",
                },
            )
            await db.flush()
            inbound = await db.get(ChatMessage, execution.inbound_message_id)
            if inbound is None:
                raise WebExecutionQueueError("claimed execution has no inbound message")
            return ClaimedWebExecution(
                execution=execution,
                inbound_message=inbound,
            )

    async def record_outcome(
        self,
        db: AsyncSession,
        *,
        execution_id: uuid.UUID,
        worker_id: str,
        outcome: WebExecutionOutcome,
        output_content: str | None = None,
        tools_used: list[str] | None = None,
        usage: dict | None = None,
        safe_code: str | None = None,
        duration_ms: int | None = None,
    ) -> RecordedWebExecutionOutcome:
        """Finish a claimed execution while closing the takeover race."""
        normalized_worker = worker_id.strip()
        if not normalized_worker or len(normalized_worker) > 120:
            raise InvalidWebExecutionCommandError("invalid worker id")
        try:
            normalized_outcome = WebExecutionOutcome(outcome)
        except ValueError as exc:
            raise InvalidWebExecutionCommandError("invalid execution outcome") from exc
        if duration_ms is not None and duration_ms < 0:
            raise InvalidWebExecutionCommandError("duration cannot be negative")
        if normalized_outcome == WebExecutionOutcome.COMPLETED:
            if (
                output_content is None
                or not output_content.strip()
                or len(output_content) > 16_000
                or safe_code is not None
            ):
                raise InvalidWebExecutionCommandError(
                    "completed execution requires output without an error code"
                )
        elif output_content is not None or not self._valid_safe_code(safe_code):
            raise InvalidWebExecutionCommandError(
                "failed or blocked execution requires a safe error code"
            )

        execution = (
            (
                await db.execute(
                    select(ChatExecution)
                    .where(ChatExecution.id == execution_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        if (
            execution is None
            or execution.status != "running"
            or execution.lease_owner != normalized_worker
        ):
            raise WebExecutionClaimOwnershipError(
                "web execution claim ownership was lost"
            )
        conversation = await self._get_execution_conversation(
            db,
            conversation_id=execution.conversation_id,
        )
        try:
            self._assert_automation(
                conversation,
                expected_version=execution.control_version,
            )
        except WebExecutionAutomationBlockedError:
            execution.status = "blocked"
            execution.error_code = "conversation_control_changed"
            execution.lease_owner = None
            execution.lease_expires_at = None
            await self._publish_execution_status(
                db,
                conversation=conversation,
                execution=execution,
                status="blocked",
                error_code="conversation_control_changed",
            )
            await db.flush()
            return RecordedWebExecutionOutcome(
                execution=execution,
                published=False,
            )

        inbound = await db.get(ChatMessage, execution.inbound_message_id)
        if inbound is None:
            raise WebExecutionQueueError("execution has no inbound message")
        inbound.status = "completed"
        execution.status = normalized_outcome.value
        execution.error_code = safe_code
        execution.duration_ms = duration_ms
        execution.tools_used = list(tools_used or [])
        execution.usage = dict(usage or {})
        execution.lease_owner = None
        execution.lease_expires_at = None

        if normalized_outcome == WebExecutionOutcome.COMPLETED:
            output = ChatMessage(
                conversation_id=execution.conversation_id,
                client_message_id=f"{execution.client_message_id}:assistant",
                role="assistant",
                content=output_content,
                status="completed",
                tool_names=list(tools_used or []),
            )
            db.add(output)
            await db.flush()
            execution.output_message_id = output.id
            await self._events.publish(
                db,
                conversation_id=conversation.id,
                agent_id=conversation.agent_id,
                event_type="chat.message.completed",
                visibility=ConversationEventVisibility.PUBLIC,
                payload={
                    "client_message_id": execution.client_message_id,
                    "content": output.content,
                    "execution_id": str(execution.id),
                    "message_id": str(output.id),
                    "status": "completed",
                },
            )
        elif normalized_outcome == WebExecutionOutcome.FAILED:
            await self._events.publish(
                db,
                conversation_id=conversation.id,
                agent_id=conversation.agent_id,
                event_type="chat.message.failed",
                visibility=ConversationEventVisibility.PUBLIC,
                payload={
                    "client_message_id": execution.client_message_id,
                    "error_code": safe_code,
                    "execution_id": str(execution.id),
                    "status": normalized_outcome.value,
                },
            )
        else:
            await self._publish_execution_status(
                db,
                conversation=conversation,
                execution=execution,
                status="blocked",
                error_code=safe_code,
            )
        await db.flush()
        return RecordedWebExecutionOutcome(execution=execution, published=True)

    async def recover_stale_leases(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> int:
        """Block expired work because tools may have produced uncertain effects."""
        recovered_at = now or datetime.now(timezone.utc)
        executions = list(
            (
                (
                    await db.execute(
                        select(ChatExecution)
                        .where(
                            ChatExecution.status == "running",
                            ChatExecution.lease_expires_at.is_not(None),
                            ChatExecution.lease_expires_at < recovered_at,
                        )
                        .order_by(ChatExecution.lease_expires_at, ChatExecution.id)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
        )
        for execution in executions:
            conversation = await db.get(
                ChatConversation,
                execution.conversation_id,
                populate_existing=True,
                with_for_update=True,
            )
            if conversation is None:
                raise WebExecutionQueueError("execution conversation is unavailable")
            execution.status = "blocked"
            execution.error_code = "stale_execution_lease"
            execution.lease_owner = None
            execution.lease_expires_at = None
            await self._publish_execution_status(
                db,
                conversation=conversation,
                execution=execution,
                status="blocked",
                error_code="stale_execution_lease",
            )
        if executions:
            await db.flush()
        return len(executions)

    def _eligible_statement(self, now: datetime):
        earlier = aliased(ChatExecution)
        earlier_blocking = exists(
            select(earlier.id).where(
                earlier.conversation_id == ChatExecution.conversation_id,
                earlier.queue_sequence.is_not(None),
                ChatExecution.queue_sequence.is_not(None),
                or_(
                    earlier.queue_sequence < ChatExecution.queue_sequence,
                    and_(
                        earlier.queue_sequence == ChatExecution.queue_sequence,
                        earlier.id < ChatExecution.id,
                    ),
                ),
                earlier.status.in_(self._blocking_statuses),
            )
        )
        return (
            select(ChatExecution)
            .where(
                ChatExecution.status == "queued",
                ChatExecution.available_at <= now,
                ChatExecution.queue_sequence.is_not(None),
                ~earlier_blocking,
            )
            .order_by(
                ChatExecution.available_at,
                ChatExecution.created_at,
                ChatExecution.id,
            )
            .limit(1)
        )

    async def _get_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        for_update: bool,
    ) -> ChatConversation:
        statement = (
            select(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.agent_id == agent_id,
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        conversation = (await db.execute(statement)).scalar_one_or_none()
        if conversation is None:
            raise WebExecutionConversationNotFoundError("conversation not found")
        return conversation

    @staticmethod
    async def _get_execution_conversation(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
    ) -> ChatConversation:
        conversation = (
            (
                await db.execute(
                    select(ChatConversation)
                    .where(ChatConversation.id == conversation_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        if conversation is None:
            raise WebExecutionQueueError("execution conversation is unavailable")
        return conversation

    @staticmethod
    def _assert_automation(
        conversation: ChatConversation,
        *,
        expected_version: int | None,
    ) -> None:
        if (
            expected_version is not None
            and conversation.control_version != expected_version
        ):
            raise WebExecutionAutomationBlockedError(
                "conversation control epoch changed"
            )
        if conversation.control_mode != "automated":
            raise WebExecutionAutomationBlockedError(
                "conversation automation is not active"
            )

    @staticmethod
    def _input_hash(*, content: str, locale: str) -> str:
        encoded = json.dumps(
            {"content": content, "locale": locale},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def _publish_execution_status(
        self,
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        execution: ChatExecution,
        status: str,
        error_code: str | None = None,
    ) -> ConversationEvent:
        payload = {
            "execution_id": str(execution.id),
            "status": status,
        }
        if error_code is not None:
            payload["error_code"] = error_code
        return await self._events.publish(
            db,
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            event_type="chat.execution.changed",
            visibility=ConversationEventVisibility.PUBLIC,
            payload=payload,
        )

    def _valid_safe_code(self, value: str | None) -> bool:
        return (
            value is not None and self._safe_code_pattern.fullmatch(value) is not None
        )


web_execution_queue_service = WebExecutionQueueService()
