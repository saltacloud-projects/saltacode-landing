"""Native capability that asks the active channel to collect quote contact data."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation
from app.schemas.tools import ToolExecutionContext, ToolResult
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
    conversation_event_service,
)
from app.services.tools.registry import AbstractTool, ToolRegistry

_ALLOWED_CHANNELS = frozenset({"web", "whatsapp"})
_ALLOWED_DELIVERY_CHANNELS = frozenset({"email", "whatsapp"})
_EVENT_TYPE = "commercial.contact.requested"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
_REDACTED = "[redacted]"


@dataclass(frozen=True, slots=True)
class _ScopedExecution:
    request_id: str
    channel: str
    principal_id: uuid.UUID
    conversation_id: uuid.UUID
    agent_id: uuid.UUID
    external_subject: str | None


@dataclass(frozen=True, slots=True)
class _ContactRequest:
    title: str
    summary: str
    preferred_delivery_channel: str

    def event_payload(self, *, request_id: str) -> dict[str, str]:
        return {
            "request_id": request_id,
            "title": self.title,
            "summary": self.summary,
            "preferred_delivery_channel": self.preferred_delivery_channel,
        }


class CommercialQuoteContactRequestTool(AbstractTool):
    """Request explicit contact capture without collecting or persisting PII."""

    tool_name = "commercial_quote_contact_request"

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
        event_service: ConversationEventService = conversation_event_service,
    ) -> None:
        self._session_factory = session_factory
        self._event_service = event_service

    async def invoke(
        self,
        params: dict[str, Any],
        request_id: str,
        context: ToolExecutionContext | str | None,
    ) -> ToolResult:
        try:
            execution = self._validate_context(context, request_id=request_id)
            contact_request = self._validate_params(params)
        except ValueError as exc:
            return self._error(request_id, str(exc))

        async with self._session_factory() as db:
            conversation = await self._load_scoped_conversation(db, execution)
            if conversation is None:
                return self._error(
                    request_id,
                    "The contact request is unavailable for this conversation.",
                )
            if conversation.control_mode != "automated":
                return self._error(
                    request_id,
                    "Conversation automation is not active.",
                )

            if execution.channel == "whatsapp":
                return self._whatsapp_result(request_id, contact_request)

            event_payload = contact_request.event_payload(request_id=request_id)
            event = await self._find_existing_event(db, execution)
            if event is None:
                event = await self._event_service.publish(
                    db,
                    conversation_id=execution.conversation_id,
                    agent_id=execution.agent_id,
                    event_type=_EVENT_TYPE,
                    visibility=ConversationEventVisibility.PUBLIC,
                    payload=event_payload,
                )
                await db.commit()
            elif not self._matches_existing_event(event, event_payload):
                return self._error(
                    request_id,
                    "The request identifier conflicts with a different contact request.",
                )

            return ToolResult(
                request_id=request_id,
                tool_name=self.tool_name,
                status="success",
                result={
                    "action": "show_contact_form",
                    "event_sequence": event.sequence,
                    "preferred_delivery_channel": (
                        event.payload_json["preferred_delivery_channel"]
                    ),
                    "request_id": request_id,
                    "consent_status": "not_captured",
                },
            )

    @staticmethod
    def _validate_context(
        context: ToolExecutionContext | str | None,
        *,
        request_id: str,
    ) -> _ScopedExecution:
        if not isinstance(context, ToolExecutionContext):
            raise ValueError("A complete execution context is required.")
        if context.request_id != request_id or not _REQUEST_ID_PATTERN.fullmatch(
            request_id
        ):
            raise ValueError("The request identifier is invalid.")
        if context.channel not in _ALLOWED_CHANNELS:
            raise ValueError("The contact request is unavailable for this channel.")
        try:
            principal_id = uuid.UUID(context.principal_id or "")
            conversation_id = uuid.UUID(context.conversation_id or "")
            agent_id = uuid.UUID(context.agent_id or "")
        except ValueError as exc:
            raise ValueError("A complete execution context is required.") from exc
        return _ScopedExecution(
            request_id=request_id,
            channel=context.channel,
            principal_id=principal_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            external_subject=context.external_subject,
        )

    @classmethod
    def _validate_params(cls, params: dict[str, Any]) -> _ContactRequest:
        if not isinstance(params, dict):
            raise ValueError("The contact request parameters are invalid.")
        preferred_delivery_channel = (
            str(params.get("preferred_delivery_channel") or "").strip().lower()
        )
        if preferred_delivery_channel not in _ALLOWED_DELIVERY_CHANNELS:
            raise ValueError(
                "The preferred delivery channel must be email or WhatsApp."
            )

        title = cls._sanitize_text(params.get("title"), max_length=120)
        summary = cls._sanitize_text(params.get("summary"), max_length=600)
        if not title or not summary:
            raise ValueError("A title and summary are required.")
        return _ContactRequest(
            title=title,
            summary=summary,
            preferred_delivery_channel=preferred_delivery_channel,
        )

    @staticmethod
    def _sanitize_text(value: Any, *, max_length: int) -> str:
        if not isinstance(value, str):
            return ""
        text = unicodedata.normalize("NFKC", value)
        text = "".join(
            " " if unicodedata.category(char).startswith("C") else char for char in text
        )
        text = _EMAIL_PATTERN.sub(_REDACTED, text)
        text = _PHONE_PATTERN.sub(_REDACTED, text)
        return " ".join(text.split())[:max_length].strip()

    @staticmethod
    async def _load_scoped_conversation(
        db: AsyncSession,
        execution: _ScopedExecution,
    ) -> ChatConversation | None:
        # The conversation lock is also the idempotency boundary: competing calls
        # cannot both pass the event lookup that follows this query.
        statement = (
            select(ChatConversation)
            .where(
                ChatConversation.id == execution.conversation_id,
                ChatConversation.agent_id == execution.agent_id,
                ChatConversation.principal_id == execution.principal_id,
                ChatConversation.channel == execution.channel,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if execution.external_subject:
            statement = statement.where(
                ChatConversation.external_thread_id == execution.external_subject
            )
        return (await db.execute(statement)).scalars().one_or_none()

    @staticmethod
    async def _find_existing_event(
        db: AsyncSession,
        execution: _ScopedExecution,
    ) -> ConversationEvent | None:
        return (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == execution.conversation_id,
                        ConversationEvent.agent_id == execution.agent_id,
                        ConversationEvent.event_type == _EVENT_TYPE,
                        ConversationEvent.visibility
                        == ConversationEventVisibility.PUBLIC.value,
                        ConversationEvent.payload_json["request_id"].astext
                        == execution.request_id,
                    )
                )
            )
            .scalars()
            .one_or_none()
        )

    @staticmethod
    def _matches_existing_event(
        event: ConversationEvent,
        event_payload: dict[str, str],
    ) -> bool:
        return event.payload_json == event_payload

    def _whatsapp_result(
        self,
        request_id: str,
        contact_request: _ContactRequest,
    ) -> ToolResult:
        instructions = (
            "Ask the user which contact detail they want to use for quote delivery.",
            "Ask for explicit consent to use that detail for quote delivery.",
            "Do not claim or record consent until the user explicitly confirms it.",
        )
        result = {
            "action": "request_contact_details_and_consent",
            "preferred_delivery_channel": contact_request.preferred_delivery_channel,
            "consent_status": "not_captured",
            "instructions": list(instructions),
        }
        return ToolResult(
            request_id=request_id,
            tool_name=self.tool_name,
            status="success",
            result=result,
            llm_summary=result,
        )

    def _error(self, request_id: str, message: str) -> ToolResult:
        return ToolResult(
            request_id=request_id,
            tool_name=self.tool_name,
            status="error",
            error=message,
        )


def register_commercial_quote_contact_request_tool(registry: ToolRegistry) -> None:
    """Register the built-in capability without assigning it to any agent."""
    registry.register(CommercialQuoteContactRequestTool())
