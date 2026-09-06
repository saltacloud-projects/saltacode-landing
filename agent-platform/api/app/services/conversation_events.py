"""Transactional publication and cursor reads for conversation events."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation


class ConversationEventError(Exception):
    """Base failure for conversation-event operations."""


class ConversationEventConversationNotFoundError(ConversationEventError):
    """The requested conversation is absent from the agent scope."""


class InvalidConversationEventError(ConversationEventError):
    """The event contract is invalid or unsafe to persist."""


class ConversationEventVisibility(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"


class ConversationEventService:
    """Allocate monotonic cursors while participating in the caller transaction."""

    _event_type_pattern = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9]+){1,5}$")
    _max_payload_bytes = 32_768
    _max_payload_depth = 8

    async def publish(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        event_type: str,
        visibility: ConversationEventVisibility,
        payload: Mapping[str, Any],
    ) -> ConversationEvent:
        """Append one event without committing the caller's transaction."""
        normalized_type = event_type.strip()
        if not self._event_type_pattern.fullmatch(normalized_type):
            raise InvalidConversationEventError("invalid event type")
        try:
            normalized_visibility = ConversationEventVisibility(visibility)
        except ValueError as exc:
            raise InvalidConversationEventError("invalid event visibility") from exc
        normalized_payload = self._normalize_payload(payload)

        conversation = (
            (
                await db.execute(
                    select(ChatConversation)
                    .where(
                        ChatConversation.id == conversation_id,
                        ChatConversation.agent_id == agent_id,
                    )
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        if conversation is None:
            raise ConversationEventConversationNotFoundError("conversation not found")

        event = ConversationEvent(
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            sequence=conversation.next_event_sequence,
            event_type=normalized_type,
            visibility=normalized_visibility.value,
            payload_json=normalized_payload,
        )
        conversation.next_event_sequence += 1
        db.add(event)
        await db.flush()
        return event

    async def list_after(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        after_sequence: int,
        limit: int = 100,
        visibility: ConversationEventVisibility | None = None,
    ) -> list[ConversationEvent]:
        """Read a strictly increasing page after the supplied cursor."""
        if after_sequence < 0:
            raise InvalidConversationEventError("event cursor cannot be negative")
        if not 1 <= limit <= 500:
            raise InvalidConversationEventError("event limit must be between 1 and 500")

        conversation_exists = (
            await db.execute(
                select(ChatConversation.id).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if conversation_exists is None:
            raise ConversationEventConversationNotFoundError("conversation not found")

        statement = select(ConversationEvent).where(
            ConversationEvent.conversation_id == conversation_id,
            ConversationEvent.agent_id == agent_id,
            ConversationEvent.sequence > after_sequence,
        )
        if visibility is not None:
            try:
                normalized_visibility = ConversationEventVisibility(visibility)
            except ValueError as exc:
                raise InvalidConversationEventError("invalid event visibility") from exc
            statement = statement.where(
                ConversationEvent.visibility == normalized_visibility.value
            )
        rows = await db.execute(
            statement.order_by(ConversationEvent.sequence).limit(limit)
        )
        return list(rows.scalars().all())

    def _normalize_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise InvalidConversationEventError("event payload must be an object")
        self._assert_depth(dict(payload), depth=1)
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
            raise InvalidConversationEventError(
                "event payload must be valid JSON"
            ) from exc
        if len(encoded) > self._max_payload_bytes:
            raise InvalidConversationEventError("event payload is too large")
        return normalized

    def _assert_depth(self, value: Any, *, depth: int) -> None:
        if depth > self._max_payload_depth:
            raise InvalidConversationEventError("event payload is too deeply nested")
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise InvalidConversationEventError(
                        "event payload keys must be strings"
                    )
                self._assert_depth(child, depth=depth + 1)
        elif isinstance(value, list):
            for child in value:
                self._assert_depth(child, depth=depth + 1)


conversation_event_service = ConversationEventService()
