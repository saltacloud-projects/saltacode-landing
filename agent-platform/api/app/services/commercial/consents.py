"""Append-only commercial-consent application policy."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.services.commercial.contacts import (
    ContactSourceMismatchError,
    assert_agent_principal_scope,
    load_contact,
    validate_contact_source,
)


class ConsentPurpose(StrEnum):
    CONVERSATION_STORAGE = "conversation_storage"
    QUOTE_DELIVERY = "quote_delivery"
    COMMERCIAL_FOLLOW_UP = "commercial_follow_up"
    MARKETING = "marketing"


class ConsentAction(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class ConsentServiceError(Exception):
    """Base error for consent policy failures."""


class ConsentSubjectMismatchError(ConsentServiceError):
    """Consent evidence references inconsistent principal or contact data."""


class ConsentIdempotencyConflictError(ConsentServiceError):
    """An idempotency key was reused for a different consent command."""


class InvalidConsentCommandError(ConsentServiceError):
    """A consent command is incomplete or internally contradictory."""


@dataclass(frozen=True, slots=True)
class ConsentResult:
    record: ConsentRecord
    created: bool


@dataclass(frozen=True, slots=True)
class EffectiveConsent:
    granted: bool
    record: ConsentRecord | None


class ConsentService:
    """Record immutable consent evidence within the caller's transaction."""

    async def record(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        principal_id: uuid.UUID,
        purpose: ConsentPurpose | str,
        action: ConsentAction | str,
        policy_version: str,
        channel: str,
        locale: str,
        source_conversation_id: uuid.UUID,
        source_channel_identity_id: uuid.UUID,
        correlation_id: str,
        idempotency_key: str,
        contact_id: uuid.UUID | None = None,
        contact_point_id: uuid.UUID | None = None,
        expires_at: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> ConsentResult:
        normalized_purpose = _enum_value(ConsentPurpose, purpose, "purpose")
        normalized_action = _enum_value(ConsentAction, action, "action")
        normalized_policy = _required_text(policy_version, "policy_version", 80)
        normalized_channel = _required_text(channel, "channel", 30).casefold()
        normalized_locale = _required_text(locale, "locale", 20)
        normalized_correlation = _required_text(
            correlation_id,
            "correlation_id",
            120,
        )
        normalized_key = _required_text(idempotency_key, "idempotency_key", 220)
        event_time = _aware_utc(occurred_at or datetime.now(UTC), "occurred_at")
        normalized_expiration = (
            _aware_utc(expires_at, "expires_at") if expires_at is not None else None
        )
        if normalized_action is ConsentAction.REVOKE and normalized_expiration:
            raise InvalidConsentCommandError("revocations cannot expire")
        if normalized_expiration is not None and normalized_expiration <= event_time:
            raise InvalidConsentCommandError("consent expiration must be in the future")

        conversation, _ = await validate_contact_source(
            db,
            agent_id=agent_id,
            principal_id=principal_id,
            conversation_id=source_conversation_id,
            channel_identity_id=source_channel_identity_id,
        )
        if conversation.channel != normalized_channel:
            raise ContactSourceMismatchError(
                "consent channel does not match source conversation"
            )
        contact = None
        if contact_id is not None:
            contact = await load_contact(db, contact_id=contact_id)
            if contact.principal_id != principal_id:
                raise ConsentSubjectMismatchError(
                    "contact does not belong to principal"
                )
        if contact_point_id is not None:
            if contact is None:
                raise ConsentSubjectMismatchError(
                    "contact point consent requires a contact"
                )
            contact_point = await db.get(ContactPoint, contact_point_id)
            if contact_point is None or contact_point.contact_id != contact.id:
                raise ConsentSubjectMismatchError(
                    "contact point does not belong to contact"
                )

        command_hash = _command_hash(
            agent_id=agent_id,
            principal_id=principal_id,
            contact_id=contact_id,
            contact_point_id=contact_point_id,
            purpose=normalized_purpose,
            action=normalized_action,
            policy_version=normalized_policy,
            channel=normalized_channel,
            locale=normalized_locale,
            source_conversation_id=source_conversation_id,
            source_channel_identity_id=source_channel_identity_id,
            expires_at=normalized_expiration,
        )
        existing = (
            await db.execute(
                select(ConsentRecord).where(
                    ConsentRecord.agent_id == agent_id,
                    ConsentRecord.idempotency_key == normalized_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ConsentIdempotencyConflictError(
                    "consent idempotency key belongs to another command"
                )
            return ConsentResult(record=existing, created=False)

        record = ConsentRecord(
            id=uuid.uuid5(agent_id, f"consent:{normalized_key}"),
            principal_id=principal_id,
            contact_id=contact_id,
            contact_point_id=contact_point_id,
            agent_id=agent_id,
            purpose=normalized_purpose,
            action=normalized_action,
            policy_version=normalized_policy,
            channel=normalized_channel,
            locale=normalized_locale,
            source_conversation_id=source_conversation_id,
            source_channel_identity_id=source_channel_identity_id,
            correlation_id=normalized_correlation,
            idempotency_key=normalized_key,
            command_hash=command_hash,
            occurred_at=event_time,
            expires_at=normalized_expiration,
        )
        db.add(record)
        await db.flush()
        return ConsentResult(record=record, created=True)

    async def effective(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        principal_id: uuid.UUID,
        purpose: ConsentPurpose | str,
        contact_point_id: uuid.UUID | None = None,
        at: datetime | None = None,
    ) -> EffectiveConsent:
        normalized_purpose = _enum_value(ConsentPurpose, purpose, "purpose")
        await assert_agent_principal_scope(
            db,
            agent_id=agent_id,
            principal_id=principal_id,
        )
        if contact_point_id is not None:
            contact_point = await db.get(ContactPoint, contact_point_id)
            contact = (
                await db.get(Contact, contact_point.contact_id)
                if contact_point is not None
                else None
            )
            if contact is None or contact.principal_id != principal_id:
                raise ConsentSubjectMismatchError(
                    "contact point does not belong to principal"
                )

        point_filter = (
            ConsentRecord.contact_point_id.is_(None)
            if contact_point_id is None
            else ConsentRecord.contact_point_id == contact_point_id
        )
        record = (
            await db.execute(
                select(ConsentRecord)
                .where(
                    ConsentRecord.agent_id == agent_id,
                    ConsentRecord.principal_id == principal_id,
                    ConsentRecord.purpose == normalized_purpose,
                    point_filter,
                )
                .order_by(
                    ConsentRecord.occurred_at.desc(),
                    ConsentRecord.created_at.desc(),
                    ConsentRecord.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        effective_at = _aware_utc(at or datetime.now(UTC), "at")
        granted = bool(
            record is not None
            and record.action == ConsentAction.GRANT
            and (record.expires_at is None or record.expires_at > effective_at)
        )
        return EffectiveConsent(granted=granted, record=record)


def _enum_value(enum_type, value, field: str):
    try:
        return enum_type(value)
    except ValueError as exc:
        raise InvalidConsentCommandError(f"invalid consent {field}") from exc


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise InvalidConsentCommandError(f"invalid consent {field}")
    return normalized


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidConsentCommandError(f"consent {field} must include a timezone")
    return value.astimezone(UTC)


def _command_hash(
    *,
    agent_id: uuid.UUID,
    principal_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    contact_point_id: uuid.UUID | None,
    purpose: ConsentPurpose,
    action: ConsentAction,
    policy_version: str,
    channel: str,
    locale: str,
    source_conversation_id: uuid.UUID,
    source_channel_identity_id: uuid.UUID,
    expires_at: datetime | None,
) -> str:
    payload = {
        "action": action.value,
        "agent_id": str(agent_id),
        "channel": channel,
        "contact_id": str(contact_id) if contact_id else None,
        "contact_point_id": str(contact_point_id) if contact_point_id else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "locale": locale,
        "policy_version": policy_version,
        "principal_id": str(principal_id),
        "purpose": purpose.value,
        "source_channel_identity_id": str(source_channel_identity_id),
        "source_conversation_id": str(source_conversation_id),
    }
    canonical = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


consent_service = ConsentService()
