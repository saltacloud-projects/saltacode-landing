"""Application service for durable, resumable web-chat sessions."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.conversation_event import ConversationEvent
from app.models.platform import (
    ChannelIdentity,
    ChatConversation,
    ChatExecution,
    ChatMessage,
    Principal,
)
from app.schemas.web_chat_v2 import (
    WebConversationEvent,
    WebEventsResponse,
    WebHistoryMessage,
    WebHistoryResponse,
    WebMessageAccepted,
    WebMessageRequest,
    WebSessionResetRequest,
    WebSessionResetResponse,
)
from app.services.agent_runtime import (
    AgentRuntimeUnavailable,
    ResolvedChannelRoute,
    agent_runtime_resolver,
)
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
)
from app.services.web_execution_queue import (
    InvalidWebExecutionCommandError,
    WebExecutionAutomationBlockedError,
    WebExecutionIdempotencyConflictError,
    WebExecutionQueueService,
)


class WebChatV2Error(Exception):
    """Base failure for the private v2 web-chat boundary."""


class WebChatRouteUnavailableError(WebChatV2Error):
    """The requested public web route cannot currently accept traffic."""


class WebChatSessionNotFoundError(WebChatV2Error):
    """The session is absent from the requested route scope."""


class WebChatConsentRequiredError(WebChatV2Error):
    """Transcript persistence was requested without affirmative consent."""


class WebChatSessionBlockedError(WebChatV2Error):
    """The session is closed or its identity is unavailable."""


class WebChatRequestConflictError(WebChatV2Error):
    """An idempotency identifier was reused for different input."""


@dataclass(frozen=True)
class _WebRouteScope:
    route: ResolvedChannelRoute
    profile: AgentProfile


class WebChatV2Service:
    """Own session scope, durable acceptance, history, events, and reset."""

    _public_event_fields = frozenset(
        {
            "client_message_id",
            "content",
            "error_code",
            "message_id",
            "mode",
            "status",
        }
    )

    def __init__(
        self,
        *,
        events: ConversationEventService | None = None,
        queue: WebExecutionQueueService | None = None,
    ) -> None:
        self._events = events or ConversationEventService()
        self._queue = queue or WebExecutionQueueService(events=self._events)

    async def accept_message(
        self,
        db: AsyncSession,
        request: WebMessageRequest,
    ) -> WebMessageAccepted:
        self._require_consent(request.consent.granted)
        scope = await self._resolve_route_scope(db, request.route_key)
        await self._lock_session_keys(db, request.route_key, request.session_id)
        conversation = await self._resolve_session(
            db,
            scope=scope,
            session_id=request.session_id,
            consent_version=request.consent.version,
        )
        if conversation.status != "active" or conversation.control_mode == "closed":
            raise WebChatSessionBlockedError("web chat session is closed")
        duplicate = await self._find_existing_acceptance(
            db,
            conversation=conversation,
            request=request,
        )
        if duplicate is not None:
            return duplicate
        if conversation.control_mode in {"human", "paused"}:
            return await self._accept_for_operator(
                db,
                conversation=conversation,
                request=request,
            )
        try:
            outcome = await self._queue.enqueue(
                db,
                conversation_id=conversation.id,
                agent_id=scope.profile.id,
                client_message_id=str(request.client_message_id),
                content=request.content,
                locale=request.locale,
            )
        except WebExecutionIdempotencyConflictError as exc:
            raise WebChatRequestConflictError(
                "client message id belongs to different input"
            ) from exc
        except WebExecutionAutomationBlockedError as exc:
            raise WebChatSessionBlockedError(
                "web chat session is not automated"
            ) from exc
        except InvalidWebExecutionCommandError as exc:
            raise WebChatV2Error("invalid durable web message") from exc
        return WebMessageAccepted(
            client_message_id=request.client_message_id,
            message_id=outcome.inbound_message.id,
            event_cursor=outcome.accepted_event.sequence,
            duplicate=outcome.duplicate,
        )

    async def _accept_for_operator(
        self,
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        request: WebMessageRequest,
    ) -> WebMessageAccepted:
        """Persist visitor input without scheduling automation."""
        client_message_id = str(request.client_message_id)
        message = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=client_message_id,
            role="user",
            content=request.content,
            status="completed",
            metadata_json={"locale": request.locale.strip()},
        )
        db.add(message)
        await db.flush()
        accepted_event = await self._events.publish(
            db,
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            event_type="chat.message.accepted",
            visibility=ConversationEventVisibility.PUBLIC,
            payload={
                "client_message_id": client_message_id,
                "message_id": str(message.id),
                "status": "accepted",
            },
        )
        return WebMessageAccepted(
            client_message_id=request.client_message_id,
            message_id=message.id,
            event_cursor=accepted_event.sequence,
            duplicate=False,
        )

    async def _find_existing_acceptance(
        self,
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        request: WebMessageRequest,
    ) -> WebMessageAccepted | None:
        client_message_id = str(request.client_message_id)
        existing = (
            (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.conversation_id == conversation.id,
                        ChatMessage.client_message_id == client_message_id,
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is None:
            return None
        if not self._same_web_input(existing, request):
            raise WebChatRequestConflictError(
                "client message id belongs to different input"
            )
        accepted_event = await self._find_message_accepted_event(
            db,
            conversation_id=conversation.id,
            message_id=existing.id,
        )
        if accepted_event is None:
            raise WebChatV2Error("stored web message has no accepted event")
        return WebMessageAccepted(
            client_message_id=request.client_message_id,
            message_id=existing.id,
            event_cursor=accepted_event.sequence,
            duplicate=True,
        )

    @staticmethod
    def _same_web_input(
        message: ChatMessage,
        request: WebMessageRequest,
    ) -> bool:
        metadata = message.metadata_json or {}
        return (
            message.role == "user"
            and message.content == request.content
            and metadata.get("locale") == request.locale.strip()
        )

    @staticmethod
    async def _find_message_accepted_event(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> ConversationEvent | None:
        return (
            (
                await db.execute(
                    select(ConversationEvent)
                    .where(
                        ConversationEvent.conversation_id == conversation_id,
                        ConversationEvent.event_type == "chat.message.accepted",
                        ConversationEvent.visibility
                        == ConversationEventVisibility.PUBLIC.value,
                        ConversationEvent.payload_json["message_id"].astext
                        == str(message_id),
                    )
                    .order_by(ConversationEvent.sequence)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def history(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        route_key: str,
        limit: int,
    ) -> WebHistoryResponse:
        scope = await self._resolve_route_scope(db, route_key)
        conversation = await self._find_session(
            db,
            scope=scope,
            session_id=session_id,
            for_update=True,
        )
        rows = list(
            (
                (
                    await db.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.conversation_id == conversation.id,
                            ChatMessage.role.in_(("user", "assistant")),
                        )
                        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        )
        rows.reverse()
        return WebHistoryResponse(
            status="closed" if conversation.status == "closed" else "active",
            control_mode=conversation.control_mode,
            latest_event_id=conversation.next_event_sequence - 1,
            messages=[
                WebHistoryMessage(
                    message_id=row.id,
                    client_message_id=row.client_message_id,
                    role=row.role,
                    content=row.content,
                    status=row.status,
                    created_at=row.created_at,
                )
                for row in rows
            ],
        )

    async def events_after(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        route_key: str,
        after: int,
        limit: int,
    ) -> WebEventsResponse:
        scope = await self._resolve_route_scope(db, route_key)
        conversation = await self._find_session(
            db,
            scope=scope,
            session_id=session_id,
            for_update=False,
        )
        events = await self._events.list_after(
            db,
            conversation_id=conversation.id,
            agent_id=scope.profile.id,
            after_sequence=after,
            limit=limit + 1,
            visibility=ConversationEventVisibility.PUBLIC,
        )
        has_more = len(events) > limit
        page = events[:limit]
        next_cursor = page[-1].sequence if page else after
        return WebEventsResponse(
            after=after,
            next_cursor=next_cursor,
            has_more=has_more,
            events=[self._public_event(event) for event in page],
        )

    async def reset_session(
        self,
        db: AsyncSession,
        request: WebSessionResetRequest,
    ) -> WebSessionResetResponse:
        self._require_consent(request.consent.granted)
        scope = await self._resolve_route_scope(db, request.route_key)
        await self._lock_session_keys(
            db,
            request.route_key,
            request.session_id,
            request.next_session_id,
        )
        current = await self._find_session(
            db,
            scope=scope,
            session_id=request.session_id,
            for_update=True,
        )
        if current.status != "closed":
            await self._close_session(db, current)
        replacement = await self._resolve_session(
            db,
            scope=scope,
            session_id=request.next_session_id,
            consent_version=request.consent.version,
        )
        if replacement.status != "active":
            raise WebChatSessionBlockedError("replacement web chat session is closed")
        return WebSessionResetResponse(
            latest_event_id=replacement.next_event_sequence - 1,
        )

    async def _resolve_route_scope(
        self,
        db: AsyncSession,
        route_key: str,
    ) -> _WebRouteScope:
        try:
            route = await agent_runtime_resolver.resolve_channel_route(
                db,
                "web",
                route_key,
            )
        except AgentRuntimeUnavailable as exc:
            raise WebChatRouteUnavailableError("web chat route is unavailable") from exc
        profile = await db.get(AgentProfile, route.route.agent_id)
        if profile is None or not profile.is_active or not profile.is_public:
            raise WebChatRouteUnavailableError("web chat route is unavailable")
        return _WebRouteScope(route=route, profile=profile)

    async def _resolve_session(
        self,
        db: AsyncSession,
        *,
        scope: _WebRouteScope,
        session_id: uuid.UUID,
        consent_version: str,
    ) -> ChatConversation:
        identity = (
            (
                await db.execute(
                    select(ChannelIdentity).where(
                        ChannelIdentity.channel == "web",
                        ChannelIdentity.route_key == scope.route.route.route_key,
                        ChannelIdentity.external_subject == str(session_id),
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if identity is None:
            principal = Principal(kind="anonymous", is_active=True)
            db.add(principal)
            await db.flush()
            identity = ChannelIdentity(
                principal_id=principal.id,
                channel="web",
                route_key=scope.route.route.route_key,
                external_subject=str(session_id),
                verified=False,
            )
            db.add(identity)
            await db.flush()
        else:
            principal = await db.get(Principal, identity.principal_id)
            if principal is None or not principal.is_active:
                raise WebChatSessionBlockedError("web chat session is unavailable")

        conversation = (
            (
                await db.execute(
                    select(ChatConversation).where(
                        ChatConversation.agent_id == scope.profile.id,
                        ChatConversation.channel == "web",
                        ChatConversation.route_key == scope.route.route.route_key,
                        ChatConversation.external_thread_id == str(session_id),
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if conversation is None:
            conversation = ChatConversation(
                agent_id=scope.profile.id,
                principal_id=identity.principal_id,
                channel="web",
                external_thread_id=str(session_id),
                route_key=scope.route.route.route_key,
                channel_route_id=scope.route.route.id,
                transcript_consent=True,
                consent_version=consent_version,
            )
            db.add(conversation)
            await db.flush()
            return conversation
        if conversation.channel_route_id not in (None, scope.route.route.id):
            raise WebChatSessionNotFoundError("web chat session was not found")
        conversation.channel_route_id = scope.route.route.id
        conversation.transcript_consent = True
        conversation.consent_version = consent_version
        return conversation

    @staticmethod
    async def _find_session(
        db: AsyncSession,
        *,
        scope: _WebRouteScope,
        session_id: uuid.UUID,
        for_update: bool,
    ) -> ChatConversation:
        statement = (
            select(ChatConversation)
            .where(
                ChatConversation.agent_id == scope.profile.id,
                ChatConversation.channel == "web",
                ChatConversation.route_key == scope.route.route.route_key,
                ChatConversation.channel_route_id == scope.route.route.id,
                ChatConversation.external_thread_id == str(session_id),
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        conversation = (await db.execute(statement)).scalars().one_or_none()
        if conversation is None:
            raise WebChatSessionNotFoundError("web chat session was not found")
        return conversation

    async def _close_session(
        self,
        db: AsyncSession,
        conversation: ChatConversation,
    ) -> None:
        conversation.status = "closed"
        conversation.control_mode = "closed"
        conversation.control_version += 1
        conversation.assigned_admin_id = None
        conversation.control_reason = "session_reset"
        conversation.control_changed_at = datetime.now(timezone.utc)
        executions = list(
            (
                (
                    await db.execute(
                        select(ChatExecution)
                        .where(
                            ChatExecution.conversation_id == conversation.id,
                            ChatExecution.status.in_(("accepted", "queued", "running")),
                        )
                        .order_by(ChatExecution.created_at, ChatExecution.id)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
        )
        for execution in executions:
            execution.status = (
                "blocked" if execution.status == "running" else "cancelled"
            )
            execution.error_code = "session_reset"
            execution.lease_owner = None
            execution.lease_expires_at = None
            await self._events.publish(
                db,
                conversation_id=conversation.id,
                agent_id=conversation.agent_id,
                event_type="chat.execution.changed",
                visibility=ConversationEventVisibility.PUBLIC,
                payload={"status": execution.status, "error_code": "session_reset"},
            )
        await self._events.publish(
            db,
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            event_type="chat.conversation.closed",
            visibility=ConversationEventVisibility.PUBLIC,
            payload={"status": "closed"},
        )
        await db.flush()

    @classmethod
    def _public_event(cls, event: ConversationEvent) -> WebConversationEvent:
        payload: dict[str, Any] = {
            key: value
            for key, value in event.payload_json.items()
            if key in cls._public_event_fields
            and isinstance(value, (str, int, float, bool, type(None)))
        }
        return WebConversationEvent(
            cursor=event.sequence,
            event_type=event.event_type,
            occurred_at=event.created_at,
            payload=payload,
        )

    @staticmethod
    def _require_consent(granted: bool) -> None:
        if not granted:
            raise WebChatConsentRequiredError(
                "transcript consent is required for durable web chat"
            )

    @staticmethod
    async def _lock_session_keys(
        db: AsyncSession,
        route_key: str,
        *session_ids: uuid.UUID,
    ) -> None:
        keys = sorted(
            {
                int.from_bytes(
                    hashlib.sha256(f"web:{route_key}:{session_id}".encode()).digest()[
                        :8
                    ],
                    byteorder="big",
                    signed=True,
                )
                for session_id in session_ids
            }
        )
        for key in keys:
            await db.execute(select(func.pg_advisory_xact_lock(key)))


web_chat_v2_service = WebChatV2Service()
