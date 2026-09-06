"""Persistence compatibility and access policy for canonical inbound messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.schemas.governance import AccessCheckRequest
from app.schemas.inbound import (
    InboundContentType,
    InboundMessageEnvelope,
    InboundReplyContext,
    InboundRouteContext,
)
from app.services.governance import governance_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.agent_profile import AgentProfile
    from app.models.platform import ChatConversation


class InboundPayloadError(ValueError):
    """A durable payload cannot be interpreted as a supported inbound contract."""


class InboundAccessDenied(PermissionError):
    """A private agent rejected the sender through its explicit access policy."""


class InboundAccessPolicyError(RuntimeError):
    """The access provider returned an internally inconsistent identity."""


@dataclass(frozen=True)
class InboundAccessIdentity:
    principal_id: uuid.UUID
    user_id: uuid.UUID | None
    display_name: str | None


def dump_inbound_payload(message: InboundMessageEnvelope) -> dict[str, Any]:
    """Persist only message fields not already owned by relational job columns."""
    payload: dict[str, Any] = {
        "schema_version": message.schema_version,
        "correlation_id": str(message.correlation_id),
        "channel": message.channel,
        "provider_thread_id": message.provider_thread_id,
        "provider_sender_id": message.provider_sender_id,
        "content": message.content,
        "content_type": message.content_type.value,
        "timestamp": message.timestamp.isoformat(),
    }
    if message.reply_context is not None:
        payload["reply_context"] = message.reply_context.model_dump(mode="json")
    if message.provider_media_id is not None:
        payload["provider_media_id"] = message.provider_media_id
    if message.interaction_id is not None:
        payload["interaction_id"] = message.interaction_id
    return payload


def load_inbound_payload(
    payload: dict[str, Any],
    *,
    channel: str,
    route_key: str,
    channel_route_id: uuid.UUID,
    channel_connection_id: uuid.UUID,
    provider_message_id: str,
    fallback_correlation_id: uuid.UUID,
    fallback_timestamp: datetime,
) -> InboundMessageEnvelope:
    """Read the current payload or upgrade one legacy WhatsApp job in memory."""
    route = InboundRouteContext(
        route_key=route_key,
        channel_route_id=channel_route_id,
        channel_connection_id=channel_connection_id,
    )
    try:
        if "schema_version" not in payload:
            return _load_legacy_whatsapp_payload(
                payload,
                route=route,
                provider_message_id=provider_message_id,
                correlation_id=fallback_correlation_id,
                fallback_timestamp=fallback_timestamp,
            )
        if payload.get("schema_version") != "1":
            raise InboundPayloadError("unsupported inbound payload version")
        if payload.get("channel") != channel:
            raise InboundPayloadError(
                "inbound payload channel does not match its route"
            )
        return InboundMessageEnvelope(
            schema_version="1",
            correlation_id=payload["correlation_id"],
            channel=channel,
            route=route,
            provider_message_id=provider_message_id,
            provider_thread_id=payload["provider_thread_id"],
            provider_sender_id=payload["provider_sender_id"],
            content=payload["content"],
            content_type=payload["content_type"],
            timestamp=payload["timestamp"],
            reply_context=payload.get("reply_context"),
            provider_media_id=payload.get("provider_media_id"),
            interaction_id=payload.get("interaction_id"),
        )
    except InboundPayloadError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InboundPayloadError("invalid inbound payload") from exc


def _load_legacy_whatsapp_payload(
    payload: dict[str, Any],
    *,
    route: InboundRouteContext,
    provider_message_id: str,
    correlation_id: uuid.UUID,
    fallback_timestamp: datetime,
) -> InboundMessageEnvelope:
    sender_id = payload["phone_number"]
    quoted_id = payload.get("quoted_id")
    if fallback_timestamp.tzinfo is None or fallback_timestamp.utcoffset() is None:
        fallback_timestamp = fallback_timestamp.replace(tzinfo=timezone.utc)
    return InboundMessageEnvelope(
        correlation_id=correlation_id,
        channel="whatsapp",
        route=route,
        provider_message_id=provider_message_id,
        provider_thread_id=sender_id,
        provider_sender_id=sender_id,
        content=payload["content"],
        content_type=InboundContentType(payload["input_type"]),
        timestamp=fallback_timestamp,
        reply_context=(
            InboundReplyContext(provider_message_id=quoted_id) if quoted_id else None
        ),
        provider_media_id=payload.get("audio_media_id"),
        interaction_id=payload.get("interactive_id"),
    )


class InboundAccessPolicy:
    """Resolve public provisional identities or private agent whitelist access."""

    async def resolve(
        self,
        db: AsyncSession,
        *,
        profile: AgentProfile,
        conversation: ChatConversation,
        sender_id: str,
        request_id: str,
        channel: str,
    ) -> InboundAccessIdentity:
        if profile.is_public:
            return InboundAccessIdentity(
                principal_id=conversation.principal_id,
                user_id=None,
                display_name=None,
            )

        access = await governance_service.check_access(
            db,
            AccessCheckRequest(
                request_id=request_id,
                phone_number=sender_id,
                channel=channel,
                agent_id=profile.id,
            ),
        )
        if not access.allowed:
            raise InboundAccessDenied(
                access.reason or "channel identity is not allowed"
            )
        if access.user is None:
            raise InboundAccessPolicyError(
                "allowed access is missing its user identity"
            )
        try:
            user_id = uuid.UUID(str(access.user["user_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise InboundAccessPolicyError(
                "allowed access has an invalid user identity"
            ) from exc
        return InboundAccessIdentity(
            principal_id=user_id,
            user_id=user_id,
            display_name=access.user.get("name"),
        )


inbound_access_policy = InboundAccessPolicy()
