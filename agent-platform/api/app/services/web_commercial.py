"""Transactional commercial-contact capture from an existing web session."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.schemas.web_commercial import (
    WebCommercialContactAccepted,
    WebCommercialContactRequest,
)
from app.services.agent_runtime import AgentRuntimeUnavailable, agent_runtime_resolver
from app.services.commercial.consents import (
    ConsentAction,
    ConsentPurpose,
    ConsentService,
)
from app.services.commercial.contact_crypto import ContactCrypto, contact_crypto
from app.services.commercial.contacts import ContactService
from app.services.commercial.handoffs import CommercialHandoffCoordinator
from app.services.conversation_events import (
    ConversationEventService,
    ConversationEventVisibility,
)


class WebCommercialError(Exception):
    """Base failure for the private web commercial-contact boundary."""


class WebCommercialRouteUnavailableError(WebCommercialError):
    """The requested route is not an active public web route."""


class WebCommercialSessionNotFoundError(WebCommercialError):
    """The session is absent from the requested route scope."""


class WebCommercialSessionBlockedError(WebCommercialError):
    """The session is closed or its durable identity is inconsistent."""


class WebCommercialRequestConflictError(WebCommercialError):
    """The client request identifier already represents different input."""


@dataclass(frozen=True, slots=True)
class _WebCommercialScope:
    agent_id: uuid.UUID
    conversation: ChatConversation
    identity: ChannelIdentity


class WebCommercialService:
    """Capture explicit contact consent and coordinate one quote opportunity."""

    def __init__(
        self,
        *,
        contacts: ContactService | None = None,
        consents: ConsentService | None = None,
        handoffs: CommercialHandoffCoordinator | None = None,
        events: ConversationEventService | None = None,
        crypto: ContactCrypto | None = None,
    ) -> None:
        self._contacts = contacts or ContactService()
        self._consents = consents or ConsentService()
        self._handoffs = handoffs or CommercialHandoffCoordinator()
        self._events = events or ConversationEventService()
        self._crypto = crypto or contact_crypto

    async def capture(
        self,
        db: AsyncSession,
        request: WebCommercialContactRequest,
    ) -> WebCommercialContactAccepted:
        await self._lock_session(db, request.route_key, request.session_id)
        scope = await self._resolve_scope(
            db,
            route_key=request.route_key,
            session_id=request.session_id,
        )
        await self._ensure_request_receipt(db, scope=scope, request=request)
        correlation_id = f"web-commercial:{request.client_request_id}"
        key_prefix = correlation_id
        contact = (
            await self._contacts.ensure_contact(
                db,
                agent_id=scope.agent_id,
                principal_id=scope.conversation.principal_id,
                source_conversation_id=scope.conversation.id,
                source_channel_identity_id=scope.identity.id,
            )
        ).contact
        point = (
            await self._contacts.add_contact_point(
                db,
                agent_id=scope.agent_id,
                contact_id=contact.id,
                kind=request.contact_kind,
                value=request.contact_value,
                source_conversation_id=scope.conversation.id,
                source_channel_identity_id=scope.identity.id,
            )
        ).contact_point
        await self._consents.record(
            db,
            agent_id=scope.agent_id,
            principal_id=scope.conversation.principal_id,
            contact_id=contact.id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.QUOTE_DELIVERY,
            action=ConsentAction.GRANT,
            policy_version=request.policy_version,
            channel="web",
            locale=request.locale,
            source_conversation_id=scope.conversation.id,
            source_channel_identity_id=scope.identity.id,
            correlation_id=correlation_id,
            idempotency_key=f"{key_prefix}:quote-delivery",
        )
        handoff = await self._handoffs.quote_requested(
            db,
            source_agent_id=scope.agent_id,
            conversation_id=scope.conversation.id,
            contact_id=contact.id,
            contact_point_id=point.id,
            title=request.title,
            summary=request.summary,
            correlation_id=correlation_id,
            idempotency_key=f"{key_prefix}:opportunity",
        )
        if handoff.created and request.commercial_follow_up_consent:
            await self._consents.record(
                db,
                agent_id=scope.agent_id,
                principal_id=scope.conversation.principal_id,
                contact_id=contact.id,
                contact_point_id=point.id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                action=ConsentAction.GRANT,
                policy_version=request.policy_version,
                channel="web",
                locale=request.locale,
                source_conversation_id=scope.conversation.id,
                source_channel_identity_id=scope.identity.id,
                correlation_id=correlation_id,
                idempotency_key=f"{key_prefix}:commercial-follow-up",
            )
        if handoff.created:
            await self._events.publish(
                db,
                conversation_id=scope.conversation.id,
                agent_id=scope.agent_id,
                event_type="commercial.opportunity.created",
                visibility=ConversationEventVisibility.PUBLIC,
                payload={
                    "client_request_id": str(request.client_request_id),
                    "opportunity_id": str(handoff.opportunity.id),
                    "preferred_delivery_channel": (request.preferred_delivery_channel),
                    "status": "accepted",
                },
            )
        return WebCommercialContactAccepted(
            opportunity_id=handoff.opportunity.id,
            target_agent_id=handoff.opportunity.assigned_agent_id,
        )

    async def _ensure_request_receipt(
        self,
        db: AsyncSession,
        *,
        scope: _WebCommercialScope,
        request: WebCommercialContactRequest,
    ) -> None:
        fingerprint = self._request_fingerprint(request)
        existing = (
            await db.execute(
                select(ConversationEvent).where(
                    ConversationEvent.conversation_id == scope.conversation.id,
                    ConversationEvent.agent_id == scope.agent_id,
                    ConversationEvent.event_type == "commercial.contact.requested",
                    ConversationEvent.visibility
                    == ConversationEventVisibility.INTERNAL,
                    ConversationEvent.payload_json["client_request_id"].astext
                    == str(request.client_request_id),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            stored_fingerprint = existing.payload_json.get("command_fingerprint")
            if not isinstance(stored_fingerprint, str) or not secrets.compare_digest(
                stored_fingerprint,
                fingerprint,
            ):
                raise WebCommercialRequestConflictError(
                    "client request id belongs to different commercial input"
                )
            return
        await self._events.publish(
            db,
            conversation_id=scope.conversation.id,
            agent_id=scope.agent_id,
            event_type="commercial.contact.requested",
            visibility=ConversationEventVisibility.INTERNAL,
            payload={
                "client_request_id": str(request.client_request_id),
                "command_fingerprint": fingerprint,
            },
        )

    def _request_fingerprint(self, request: WebCommercialContactRequest) -> str:
        normalized_contact = self._crypto.normalize(
            kind=request.contact_kind,
            value=request.contact_value,
        )
        canonical = json.dumps(
            {
                "commercial_follow_up_consent": (request.commercial_follow_up_consent),
                "contact_kind": request.contact_kind,
                "contact_value": normalized_contact,
                "locale": request.locale.strip(),
                "policy_version": request.policy_version.strip(),
                "preferred_delivery_channel": (request.preferred_delivery_channel),
                "quote_delivery_consent": request.quote_delivery_consent,
                "route_key": request.route_key,
                "session_id": str(request.session_id),
                "summary": request.summary.strip() if request.summary else None,
                "title": request.title.strip(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return self._crypto.fingerprint(
            namespace="web-commercial-request-v1",
            payload=canonical,
        )

    @staticmethod
    async def _resolve_scope(
        db: AsyncSession,
        *,
        route_key: str,
        session_id: uuid.UUID,
    ) -> _WebCommercialScope:
        try:
            resolved = await agent_runtime_resolver.resolve_channel_route(
                db,
                "web",
                route_key,
            )
        except AgentRuntimeUnavailable as exc:
            raise WebCommercialRouteUnavailableError(
                "web route is unavailable"
            ) from exc
        profile = await db.get(AgentProfile, resolved.route.agent_id)
        if profile is None or not profile.is_active or not profile.is_public:
            raise WebCommercialRouteUnavailableError("web route is unavailable")

        conversation = (
            await db.execute(
                select(ChatConversation)
                .where(
                    ChatConversation.agent_id == profile.id,
                    ChatConversation.channel == "web",
                    ChatConversation.route_key == resolved.route.route_key,
                    ChatConversation.channel_route_id == resolved.route.id,
                    ChatConversation.external_thread_id == str(session_id),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise WebCommercialSessionNotFoundError("web session was not found")
        if conversation.status != "active" or conversation.control_mode == "closed":
            raise WebCommercialSessionBlockedError("web session is closed")

        identity = (
            await db.execute(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == "web",
                    ChannelIdentity.route_key == resolved.route.route_key,
                    ChannelIdentity.external_subject == str(session_id),
                )
            )
        ).scalar_one_or_none()
        if identity is None or identity.principal_id != conversation.principal_id:
            raise WebCommercialSessionBlockedError(
                "web session identity is inconsistent"
            )
        principal = await db.get(Principal, identity.principal_id)
        if principal is None or not principal.is_active:
            raise WebCommercialSessionBlockedError(
                "web session identity is unavailable"
            )
        return _WebCommercialScope(
            agent_id=profile.id,
            conversation=conversation,
            identity=identity,
        )

    @staticmethod
    async def _lock_session(
        db: AsyncSession,
        route_key: str,
        session_id: uuid.UUID,
    ) -> None:
        lock_key = int.from_bytes(
            hashlib.sha256(f"web:{route_key}:{session_id}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await db.execute(select(func.pg_advisory_xact_lock(lock_key)))


web_commercial_service = WebCommercialService()
