"""Caller-transaction-owned application service for commercial contacts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact, ContactPoint
from app.models.platform import ChannelIdentity, ChatConversation
from app.services.commercial.contact_crypto import ContactCrypto, contact_crypto


class ContactServiceError(Exception):
    """Base error for commercial contact policy failures."""


class ContactNotFoundError(ContactServiceError):
    """A contact is absent or outside the requested agent scope."""


class ContactSourceMismatchError(ContactServiceError):
    """Conversation or channel evidence does not match the contact principal."""


class ContactSemanticConflictError(ContactServiceError):
    """A retry conflicts with already persisted contact meaning."""


@dataclass(frozen=True, slots=True)
class ContactResult:
    contact: Contact
    created: bool


@dataclass(frozen=True, slots=True)
class ContactPointResult:
    contact_point: ContactPoint
    created: bool


class ContactService:
    """Create contacts without committing or merging principals implicitly."""

    def __init__(self, *, crypto: ContactCrypto = contact_crypto) -> None:
        self._crypto = crypto

    async def ensure_contact(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        principal_id: uuid.UUID,
        source_conversation_id: uuid.UUID,
        source_channel_identity_id: uuid.UUID,
        company_name: str | None = None,
        job_title: str | None = None,
    ) -> ContactResult:
        await validate_contact_source(
            db,
            agent_id=agent_id,
            principal_id=principal_id,
            conversation_id=source_conversation_id,
            channel_identity_id=source_channel_identity_id,
        )
        normalized_company = _optional_text(company_name)
        normalized_job_title = _optional_text(job_title)
        existing = (
            await db.execute(
                select(Contact).where(Contact.principal_id == principal_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                normalized_company is not None
                and existing.company_name != normalized_company
            ) or (
                normalized_job_title is not None
                and existing.job_title != normalized_job_title
            ):
                raise ContactSemanticConflictError(
                    "existing contact has different profile attributes"
                )
            return ContactResult(contact=existing, created=False)

        contact = Contact(
            principal_id=principal_id,
            created_by_agent_id=agent_id,
            company_name=normalized_company,
            job_title=normalized_job_title,
        )
        db.add(contact)
        await db.flush()
        return ContactResult(contact=contact, created=True)

    async def add_contact_point(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        contact_id: uuid.UUID,
        kind: str,
        value: str,
        source_conversation_id: uuid.UUID,
        source_channel_identity_id: uuid.UUID,
    ) -> ContactPointResult:
        contact = await load_contact(db, contact_id=contact_id)
        await validate_contact_source(
            db,
            agent_id=agent_id,
            principal_id=contact.principal_id,
            conversation_id=source_conversation_id,
            channel_identity_id=source_channel_identity_id,
        )
        protected = self._crypto.protect(kind=kind, value=value)
        existing = (
            await db.execute(
                select(ContactPoint).where(
                    ContactPoint.contact_id == contact.id,
                    ContactPoint.kind == kind,
                    ContactPoint.lookup_hmac == protected.lookup_hmac,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return ContactPointResult(contact_point=existing, created=False)

        point = ContactPoint(
            contact_id=contact.id,
            kind=kind,
            ciphertext=protected.ciphertext,
            lookup_hmac=protected.lookup_hmac,
            masked_value=protected.masked_value,
            verification_status="unverified",
            source_conversation_id=source_conversation_id,
            source_channel_identity_id=source_channel_identity_id,
        )
        db.add(point)
        await db.flush()
        return ContactPointResult(contact_point=point, created=True)

    async def find_contact_points(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        principal_id: uuid.UUID,
        kind: str,
        value: str,
        source_conversation_id: uuid.UUID,
        source_channel_identity_id: uuid.UUID,
    ) -> list[ContactPoint]:
        await validate_contact_source(
            db,
            agent_id=agent_id,
            principal_id=principal_id,
            conversation_id=source_conversation_id,
            channel_identity_id=source_channel_identity_id,
        )
        lookup_hmac = self._crypto.lookup(kind=kind, value=value)
        rows = await db.execute(
            select(ContactPoint)
            .join(Contact, Contact.id == ContactPoint.contact_id)
            .where(
                Contact.principal_id == principal_id,
                ContactPoint.kind == kind,
                ContactPoint.lookup_hmac == lookup_hmac,
            )
            .order_by(ContactPoint.created_at, ContactPoint.id)
        )
        return list(rows.scalars().all())


async def assert_agent_principal_scope(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    principal_id: uuid.UUID,
) -> None:
    conversation_id = (
        await db.execute(
            select(ChatConversation.id)
            .where(
                ChatConversation.agent_id == agent_id,
                ChatConversation.principal_id == principal_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if conversation_id is None:
        raise ContactNotFoundError("principal not found for agent")


async def load_contact(db: AsyncSession, *, contact_id: uuid.UUID) -> Contact:
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise ContactNotFoundError("contact not found")
    return contact


async def validate_contact_source(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    principal_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel_identity_id: uuid.UUID,
) -> tuple[ChatConversation, ChannelIdentity]:
    conversation = await db.get(ChatConversation, conversation_id)
    identity = await db.get(ChannelIdentity, channel_identity_id)
    if conversation is None or identity is None:
        raise ContactSourceMismatchError("contact source evidence was not found")
    if conversation.agent_id != agent_id or conversation.principal_id != principal_id:
        raise ContactSourceMismatchError(
            "source conversation does not match agent and principal"
        )
    if identity.principal_id != principal_id:
        raise ContactSourceMismatchError(
            "source channel identity does not match principal"
        )
    if (
        identity.channel != conversation.channel
        or identity.route_key != conversation.route_key
    ):
        raise ContactSourceMismatchError(
            "source channel identity does not match conversation route"
        )
    return conversation, identity


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


contact_service = ContactService()
