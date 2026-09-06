"""Transactional queue policy for channel-neutral outbound delivery."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryEvent,
    OutboundMessage,
)
from app.models.platform import ChatConversation, ChatMessage


class OutboundSenderType(StrEnum):
    AUTOMATION = "automation"
    OPERATOR = "operator"
    SYSTEM = "system"


class OutboundKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    TEMPLATE = "template"
    INTERACTIVE = "interactive"


class DispatchOutcome(StrEnum):
    ACCEPTED = "accepted"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"


class OutboundDeliveryError(Exception):
    """Base error for durable outbound queue policy failures."""


class OutboundConversationNotFoundError(OutboundDeliveryError):
    """The conversation does not belong to the requested agent."""


class OutboundMessageNotFoundError(OutboundDeliveryError):
    """The requested message is outside the scoped conversation."""


class OutboundIdempotencyConflictError(OutboundDeliveryError):
    """An idempotency key was reused for a different command payload."""


class OutboundFenceViolationError(OutboundDeliveryError):
    """The sender does not own the current conversation-control epoch."""


class OutboundClaimOwnershipError(OutboundDeliveryError):
    """A worker attempted to complete a claim it does not own."""


class InvalidOutboundCommandError(OutboundDeliveryError):
    """The outbound command contains unsafe or invalid identifiers."""


@dataclass(frozen=True)
class OutboundEnqueueResult:
    message: OutboundMessage
    duplicate: bool


@dataclass(frozen=True)
class ClaimedOutbound:
    message: OutboundMessage
    attempt: OutboundAttempt


class OutboundDeliveryService:
    """Serialize enqueue and per-conversation FIFO claims in PostgreSQL."""

    # Provider acceptance closes dispatch ordering. Delivery/read callbacks can
    # arrive later; only work not accepted with certainty blocks the next command.
    _blocking_statuses = ("queued", "dispatching", "delivery_unknown")
    _safe_code_pattern = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
    _mime_pattern = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
    )
    _max_payload_bytes = 65_536

    async def enqueue(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        chat_message_id: uuid.UUID | None,
        kind: OutboundKind,
        payload: Mapping[str, Any],
        sender_type: OutboundSenderType,
        control_version: int,
        idempotency_key: str,
        correlation_id: str,
        sender_admin_id: uuid.UUID | None = None,
    ) -> OutboundEnqueueResult:
        """Enqueue once inside the caller's transaction without provider I/O."""
        normalized_key = idempotency_key.strip()
        normalized_correlation = correlation_id.strip()
        if not normalized_key or len(normalized_key) > 255:
            raise InvalidOutboundCommandError("invalid idempotency key")
        if not normalized_correlation or len(normalized_correlation) > 120:
            raise InvalidOutboundCommandError("invalid correlation id")
        normalized_payload = self._normalize_payload(kind=kind, payload=payload)

        conversation = await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=True,
        )
        if conversation.channel_route_id is None:
            raise OutboundFenceViolationError(
                "outbound delivery requires an explicit channel route"
            )
        destination = conversation.external_thread_id.strip()
        if not destination or len(destination) > 255:
            raise InvalidOutboundCommandError("invalid outbound destination")

        if chat_message_id is not None:
            chat_message = await db.get(ChatMessage, chat_message_id)
            if chat_message is None or chat_message.conversation_id != conversation.id:
                raise OutboundMessageNotFoundError("chat message not found")

        command_hash = self._command_hash(
            conversation=conversation,
            destination=destination,
            chat_message_id=chat_message_id,
            kind=kind,
            payload=normalized_payload,
            sender_type=sender_type,
            sender_admin_id=sender_admin_id,
            control_version=control_version,
        )
        existing = (
            await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.conversation_id == conversation.id,
                    OutboundMessage.idempotency_key == normalized_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.payload_hash != command_hash:
                raise OutboundIdempotencyConflictError(
                    "idempotency key belongs to another outbound command"
                )
            return OutboundEnqueueResult(message=existing, duplicate=True)

        self._assert_sender_fence(
            conversation,
            sender_type=sender_type,
            sender_admin_id=sender_admin_id,
            control_version=control_version,
        )
        sequence = conversation.next_outbound_sequence
        conversation.next_outbound_sequence += 1
        message = OutboundMessage(
            conversation_id=conversation.id,
            agent_id=agent_id,
            channel_route_id=conversation.channel_route_id,
            chat_message_id=chat_message_id,
            kind=kind,
            payload_json=normalized_payload,
            destination=destination,
            sender_type=sender_type,
            sender_admin_id=sender_admin_id,
            control_version=control_version,
            sequence=sequence,
            idempotency_key=normalized_key,
            payload_hash=command_hash,
            correlation_id=normalized_correlation,
            status="queued",
            last_attempt_number=0,
        )
        db.add(message)
        await db.flush()
        self._add_event(
            db,
            message=message,
            event_type="enqueued",
            from_status=None,
            to_status="queued",
            actor_type=sender_type,
            actor_id=str(sender_admin_id) if sender_admin_id else None,
        )
        await db.flush()
        return OutboundEnqueueResult(message=message, duplicate=False)

    async def claim_next(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        stale_before: datetime,
        now: datetime | None = None,
    ) -> ClaimedOutbound | None:
        """Claim one eligible head while allowing other conversations in parallel."""
        normalized_worker_id = worker_id.strip()
        if not normalized_worker_id or len(normalized_worker_id) > 120:
            raise InvalidOutboundCommandError("invalid worker id")
        claimed_at = now or datetime.now(timezone.utc)
        await self.recover_stale_dispatches(
            db,
            stale_before=stale_before,
            actor_id=normalized_worker_id,
        )

        while True:
            message = (
                (
                    await db.execute(
                        self._eligible_head_statement().with_for_update(
                            skip_locked=True
                        )
                    )
                )
                .scalars()
                .first()
            )
            if message is None:
                return None

            conversation = await self._get_conversation(
                db,
                conversation_id=message.conversation_id,
                agent_id=message.agent_id,
                for_update=True,
            )
            try:
                self._assert_sender_fence(
                    conversation,
                    sender_type=OutboundSenderType(message.sender_type),
                    sender_admin_id=message.sender_admin_id,
                    control_version=message.control_version,
                )
            except OutboundFenceViolationError:
                self._cancel_stale_message(db, message=message)
                await db.flush()
                continue

            previous_status = message.status
            message.status = "dispatching"
            message.last_attempt_number += 1
            message.locked_by = normalized_worker_id
            message.locked_at = claimed_at
            attempt = OutboundAttempt(
                outbound_message_id=message.id,
                attempt_number=message.last_attempt_number,
                worker_id=normalized_worker_id,
                control_version=message.control_version,
            )
            db.add(attempt)
            await db.flush()
            self._add_event(
                db,
                message=message,
                attempt=attempt,
                event_type="claimed",
                from_status=previous_status,
                to_status="dispatching",
                actor_type="worker",
                actor_id=normalized_worker_id,
            )
            await db.flush()
            return ClaimedOutbound(message=message, attempt=attempt)

    async def recover_stale_dispatches(
        self,
        db: AsyncSession,
        *,
        stale_before: datetime,
        actor_id: str,
    ) -> int:
        """Fail closed when provider acceptance may have happened before a crash."""
        normalized_actor_id = actor_id.strip()
        if not normalized_actor_id or len(normalized_actor_id) > 120:
            raise InvalidOutboundCommandError("invalid recovery actor id")
        stale_messages = list(
            (
                await db.execute(
                    select(OutboundMessage)
                    .where(
                        OutboundMessage.status == "dispatching",
                        OutboundMessage.locked_at.is_not(None),
                        OutboundMessage.locked_at < stale_before,
                    )
                    .order_by(OutboundMessage.created_at, OutboundMessage.id)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for message in stale_messages:
            attempt = await self._latest_attempt(db, message)
            previous_status = message.status
            message.status = "delivery_unknown"
            message.locked_by = None
            message.locked_at = None
            self._add_event(
                db,
                message=message,
                attempt=attempt,
                event_type="delivery_unknown",
                from_status=previous_status,
                to_status="delivery_unknown",
                actor_type="worker",
                actor_id=normalized_actor_id,
                safe_code="stale_dispatch",
            )
        if stale_messages:
            await db.flush()
        return len(stale_messages)

    async def revalidate_claim_for_dispatch(
        self,
        db: AsyncSession,
        *,
        outbound_message_id: uuid.UUID,
        attempt_id: uuid.UUID,
        worker_id: str,
    ) -> OutboundMessage | None:
        """Lock and fence a committed claim immediately before provider I/O."""
        normalized_worker_id = self._normalize_worker_id(worker_id)
        message, attempt = await self._lock_owned_dispatch(
            db,
            outbound_message_id=outbound_message_id,
            attempt_id=attempt_id,
            worker_id=normalized_worker_id,
        )
        conversation = await self._get_conversation(
            db,
            conversation_id=message.conversation_id,
            agent_id=message.agent_id,
            for_update=True,
        )
        try:
            self._assert_sender_fence(
                conversation,
                sender_type=OutboundSenderType(message.sender_type),
                sender_admin_id=message.sender_admin_id,
                control_version=message.control_version,
            )
        except OutboundFenceViolationError:
            self._cancel_stale_message(db, message=message, attempt=attempt)
            await db.flush()
            return None
        return message

    async def record_dispatch_outcome(
        self,
        db: AsyncSession,
        *,
        outbound_message_id: uuid.UUID,
        attempt_id: uuid.UUID,
        worker_id: str,
        outcome: DispatchOutcome,
        provider_message_id: str | None = None,
        safe_code: str | None = None,
        occurred_at: datetime | None = None,
    ) -> OutboundMessage:
        """Persist a safe provider outcome without storing response bodies."""
        normalized_worker_id = self._normalize_worker_id(worker_id)
        normalized_provider_message_id = (
            provider_message_id.strip() if provider_message_id is not None else None
        )
        if safe_code is not None and not self._safe_code_pattern.fullmatch(safe_code):
            raise InvalidOutboundCommandError("invalid safe result code")
        if outcome == DispatchOutcome.ACCEPTED:
            if (
                not normalized_provider_message_id
                or len(normalized_provider_message_id) > 255
            ):
                raise InvalidOutboundCommandError(
                    "accepted delivery requires a provider message id"
                )
        elif normalized_provider_message_id is not None:
            raise InvalidOutboundCommandError(
                "provider message id is valid only for accepted delivery"
            )
        if outcome != DispatchOutcome.ACCEPTED and safe_code is None:
            raise InvalidOutboundCommandError(
                "failed or uncertain delivery requires a safe result code"
            )
        message, attempt = await self._lock_owned_dispatch(
            db,
            outbound_message_id=outbound_message_id,
            attempt_id=attempt_id,
            worker_id=normalized_worker_id,
        )

        previous_status = message.status
        message.status = outcome
        message.locked_by = None
        message.locked_at = None
        event_time = occurred_at or datetime.now(timezone.utc)
        if outcome == DispatchOutcome.ACCEPTED:
            message.provider_message_id = normalized_provider_message_id
            message.accepted_at = event_time
        self._add_event(
            db,
            message=message,
            attempt=attempt,
            event_type=outcome,
            from_status=previous_status,
            to_status=outcome,
            actor_type="worker",
            actor_id=normalized_worker_id,
            safe_code=safe_code,
        )
        await db.flush()
        return message

    def _eligible_head_statement(self):
        earlier = aliased(OutboundMessage)
        earlier_blocking = exists(
            select(earlier.id).where(
                earlier.conversation_id == OutboundMessage.conversation_id,
                earlier.sequence < OutboundMessage.sequence,
                earlier.status.in_(self._blocking_statuses),
            )
        )
        return (
            select(OutboundMessage)
            .where(
                OutboundMessage.status == "queued",
                ~earlier_blocking,
            )
            .order_by(OutboundMessage.created_at, OutboundMessage.id)
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
            raise OutboundConversationNotFoundError("conversation not found")
        return conversation

    @staticmethod
    def _assert_sender_fence(
        conversation: ChatConversation,
        *,
        sender_type: OutboundSenderType,
        sender_admin_id: uuid.UUID | None,
        control_version: int,
    ) -> None:
        if conversation.control_version != control_version:
            raise OutboundFenceViolationError("conversation control epoch changed")
        if sender_type == OutboundSenderType.OPERATOR:
            if (
                conversation.control_mode != "human"
                or sender_admin_id is None
                or conversation.assigned_admin_id != sender_admin_id
            ):
                raise OutboundFenceViolationError(
                    "operator does not own this conversation"
                )
            return
        if sender_admin_id is not None:
            raise OutboundFenceViolationError(
                "non-operator sender cannot impersonate an administrator"
            )
        if conversation.control_mode != "automated":
            raise OutboundFenceViolationError(
                "automation is blocked for this conversation"
            )

    @staticmethod
    def _command_hash(
        *,
        conversation: ChatConversation,
        destination: str,
        chat_message_id: uuid.UUID | None,
        kind: OutboundKind,
        payload: Mapping[str, Any],
        sender_type: OutboundSenderType,
        sender_admin_id: uuid.UUID | None,
        control_version: int,
    ) -> str:
        payload = {
            "agent_id": str(conversation.agent_id),
            "channel_route_id": str(conversation.channel_route_id),
            "chat_message_id": str(chat_message_id) if chat_message_id else None,
            "control_version": control_version,
            "conversation_id": str(conversation.id),
            "destination": destination,
            "kind": kind,
            "payload": payload,
            "sender_admin_id": str(sender_admin_id) if sender_admin_id else None,
            "sender_type": sender_type,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _normalize_payload(
        self,
        *,
        kind: OutboundKind,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise InvalidOutboundCommandError("outbound payload must be an object")
        try:
            encoded = json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
            normalized = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise InvalidOutboundCommandError(
                "outbound payload must be valid JSON"
            ) from exc
        if len(encoded) > self._max_payload_bytes:
            raise InvalidOutboundCommandError("outbound payload is too large")

        validators = {
            OutboundKind.TEXT: self._validate_text_payload,
            OutboundKind.IMAGE: self._validate_file_payload,
            OutboundKind.DOCUMENT: self._validate_file_payload,
            OutboundKind.TEMPLATE: self._validate_template_payload,
            OutboundKind.INTERACTIVE: self._validate_interactive_payload,
        }
        try:
            validator = validators[OutboundKind(kind)]
        except (KeyError, ValueError) as exc:
            raise InvalidOutboundCommandError("invalid outbound kind") from exc
        validator(normalized, kind=OutboundKind(kind))
        return normalized

    @staticmethod
    def _validate_text_payload(
        payload: dict[str, Any],
        *,
        kind: OutboundKind,
    ) -> None:
        del kind
        OutboundDeliveryService._require_exact_keys(payload, required={"text"})
        OutboundDeliveryService._require_text(
            payload["text"], field="text", max_length=16_384
        )

    def _validate_file_payload(
        self,
        payload: dict[str, Any],
        *,
        kind: OutboundKind,
    ) -> None:
        self._require_exact_keys(
            payload,
            required={"storage_key", "name", "mime"},
            optional={"caption"},
        )
        storage_key = self._require_text(
            payload["storage_key"], field="storage_key", max_length=500
        )
        if storage_key.startswith("/") or ".." in storage_key.split("/"):
            raise InvalidOutboundCommandError("invalid storage_key")
        self._require_text(payload["name"], field="name", max_length=500)
        mime = self._require_text(payload["mime"], field="mime", max_length=160)
        if not self._mime_pattern.fullmatch(mime):
            raise InvalidOutboundCommandError("invalid mime")
        if kind == OutboundKind.IMAGE and not mime.lower().startswith("image/"):
            raise InvalidOutboundCommandError("image payload requires an image mime")
        if "caption" in payload:
            self._require_text(
                payload["caption"],
                field="caption",
                max_length=4_096,
                allow_empty=True,
            )

    def _validate_template_payload(
        self,
        payload: dict[str, Any],
        *,
        kind: OutboundKind,
    ) -> None:
        del kind
        self._require_exact_keys(
            payload,
            required={"template_key", "language"},
            optional={"parameters"},
        )
        self._require_text(
            payload["template_key"], field="template_key", max_length=160
        )
        self._require_text(payload["language"], field="language", max_length=35)
        parameters = payload.get("parameters", [])
        if not isinstance(parameters, list) or len(parameters) > 100:
            raise InvalidOutboundCommandError("invalid template parameters")
        for parameter in parameters:
            self._require_text(
                parameter,
                field="template parameter",
                max_length=4_096,
                allow_empty=True,
            )

    def _validate_interactive_payload(
        self,
        payload: dict[str, Any],
        *,
        kind: OutboundKind,
    ) -> None:
        del kind
        self._require_exact_keys(
            payload,
            required={"body", "actions"},
            optional={"header", "footer"},
        )
        self._require_text(payload["body"], field="body", max_length=4_096)
        for optional_field in ("header", "footer"):
            if optional_field in payload:
                self._require_text(
                    payload[optional_field],
                    field=optional_field,
                    max_length=1_024,
                    allow_empty=True,
                )
        actions = payload["actions"]
        if not isinstance(actions, list) or not actions or len(actions) > 20:
            raise InvalidOutboundCommandError("invalid interactive actions")
        for action in actions:
            if not isinstance(action, dict):
                raise InvalidOutboundCommandError("invalid interactive action")
            self._require_exact_keys(
                action,
                required={"id", "label"},
                optional={"description"},
            )
            self._require_text(action["id"], field="action id", max_length=160)
            self._require_text(action["label"], field="action label", max_length=160)
            if "description" in action:
                self._require_text(
                    action["description"],
                    field="action description",
                    max_length=500,
                    allow_empty=True,
                )

    @staticmethod
    def _require_exact_keys(
        payload: Mapping[str, Any],
        *,
        required: set[str],
        optional: set[str] | None = None,
    ) -> None:
        allowed = required | (optional or set())
        payload_keys = set(payload)
        if not required.issubset(payload_keys) or not payload_keys.issubset(allowed):
            raise InvalidOutboundCommandError("invalid outbound payload fields")

    @staticmethod
    def _require_text(
        value: Any,
        *,
        field: str,
        max_length: int,
        allow_empty: bool = False,
    ) -> str:
        if not isinstance(value, str) or len(value) > max_length:
            raise InvalidOutboundCommandError(f"invalid {field}")
        if not allow_empty and not value.strip():
            raise InvalidOutboundCommandError(f"invalid {field}")
        return value

    async def _latest_attempt(
        self,
        db: AsyncSession,
        message: OutboundMessage,
    ) -> OutboundAttempt | None:
        if message.last_attempt_number <= 0:
            return None
        return (
            await db.execute(
                select(OutboundAttempt).where(
                    OutboundAttempt.outbound_message_id == message.id,
                    OutboundAttempt.attempt_number == message.last_attempt_number,
                )
            )
        ).scalar_one_or_none()

    async def _lock_owned_dispatch(
        self,
        db: AsyncSession,
        *,
        outbound_message_id: uuid.UUID,
        attempt_id: uuid.UUID,
        worker_id: str,
    ) -> tuple[OutboundMessage, OutboundAttempt]:
        message = (
            (
                await db.execute(
                    select(OutboundMessage)
                    .where(OutboundMessage.id == outbound_message_id)
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        attempt = await db.get(OutboundAttempt, attempt_id)
        if (
            message is None
            or attempt is None
            or attempt.outbound_message_id != outbound_message_id
            or attempt.worker_id != worker_id
            or message.locked_by != worker_id
            or message.status != "dispatching"
        ):
            raise OutboundClaimOwnershipError("outbound claim ownership was lost")
        return message, attempt

    @staticmethod
    def _normalize_worker_id(worker_id: str) -> str:
        normalized_worker_id = worker_id.strip()
        if not normalized_worker_id or len(normalized_worker_id) > 120:
            raise InvalidOutboundCommandError("invalid worker id")
        return normalized_worker_id

    def _cancel_stale_message(
        self,
        db: AsyncSession,
        *,
        message: OutboundMessage,
        attempt: OutboundAttempt | None = None,
    ) -> None:
        previous_status = message.status
        message.status = "cancelled"
        message.locked_by = None
        message.locked_at = None
        self._add_event(
            db,
            message=message,
            attempt=attempt,
            event_type="cancelled",
            from_status=previous_status,
            to_status="cancelled",
            actor_type="system",
            actor_id=None,
            safe_code="control_fence_changed",
        )

    @staticmethod
    def _add_event(
        db: AsyncSession,
        *,
        message: OutboundMessage,
        event_type: str,
        from_status: str | None,
        to_status: str,
        actor_type: str,
        actor_id: str | None,
        attempt: OutboundAttempt | None = None,
        safe_code: str | None = None,
    ) -> None:
        db.add(
            OutboundDeliveryEvent(
                outbound_message_id=message.id,
                attempt_id=attempt.id if attempt else None,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_type=actor_type,
                actor_id=actor_id,
                safe_code=safe_code,
            )
        )


outbound_delivery_service = OutboundDeliveryService()
