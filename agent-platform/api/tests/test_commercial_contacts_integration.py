"""PostgreSQL integration coverage for contacts and commercial consent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.services.commercial.consents import (
    ConsentAction,
    ConsentIdempotencyConflictError,
    ConsentPurpose,
    ConsentService,
    ConsentSubjectMismatchError,
)
from app.services.commercial.contact_crypto import ContactCrypto
from app.services.commercial.contacts import (
    ContactNotFoundError,
    ContactService,
    ContactSourceMismatchError,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class CommercialContext:
    agent_id: UUID
    other_agent_id: UUID
    principal_id: UUID
    other_principal_id: UUID
    conversation_id: UUID
    mismatched_conversation_id: UUID
    identity_id: UUID
    mismatched_identity_id: UUID


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
def contact_crypto_keys(monkeypatch, tmp_path) -> None:
    encryption_key = tmp_path / "contact-data.key"
    lookup_key = tmp_path / "contact-lookup.key"
    encryption_key.write_bytes(Fernet.generate_key())
    lookup_key.write_bytes(b"integration-lookup-key-with-thirty-two-bytes")
    monkeypatch.setattr(settings, "contact_encryption_key_file", encryption_key)
    monkeypatch.setattr(settings, "contact_lookup_hmac_key_file", lookup_key)


@pytest.fixture
async def commercial_context() -> CommercialContext:
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        agent = _agent(slug=f"commercial-{suffix}")
        other_agent = _agent(slug=f"commercial-other-{suffix}")
        principal = Principal(display_name="Commercial integration")
        other_principal = Principal(display_name="Other commercial integration")
        db.add_all([agent, other_agent, principal, other_principal])
        await db.flush()

        identity = ChannelIdentity(
            principal_id=principal.id,
            channel="web",
            route_key="commercial-test",
            external_subject=f"visitor-{suffix}",
        )
        mismatched_identity = ChannelIdentity(
            principal_id=other_principal.id,
            channel="web",
            route_key="commercial-test",
            external_subject=f"other-visitor-{suffix}",
        )
        db.add_all([identity, mismatched_identity])
        await db.flush()
        conversation = ChatConversation(
            agent_id=agent.id,
            principal_id=principal.id,
            channel="web",
            route_key="commercial-test",
            external_thread_id=f"thread-{suffix}",
            transcript_consent=True,
            consent_version="transcript-v1",
        )
        mismatched_conversation = ChatConversation(
            agent_id=agent.id,
            principal_id=other_principal.id,
            channel="web",
            route_key="commercial-test",
            external_thread_id=f"other-thread-{suffix}",
        )
        db.add_all([conversation, mismatched_conversation])
        await db.commit()
        context = CommercialContext(
            agent_id=agent.id,
            other_agent_id=other_agent.id,
            principal_id=principal.id,
            other_principal_id=other_principal.id,
            conversation_id=conversation.id,
            mismatched_conversation_id=mismatched_conversation.id,
            identity_id=identity.id,
            mismatched_identity_id=mismatched_identity.id,
        )

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ConsentRecord).where(
                    ConsentRecord.agent_id.in_(
                        [context.agent_id, context.other_agent_id]
                    )
                )
            )
            await db.execute(
                delete(Contact).where(
                    Contact.principal_id.in_(
                        [context.principal_id, context.other_principal_id]
                    )
                )
            )
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id.in_(
                        [context.conversation_id, context.mismatched_conversation_id]
                    )
                )
            )
            await db.execute(
                delete(ChannelIdentity).where(
                    ChannelIdentity.id.in_(
                        [context.identity_id, context.mismatched_identity_id]
                    )
                )
            )
            await db.execute(
                delete(Principal).where(
                    Principal.id.in_([context.principal_id, context.other_principal_id])
                )
            )
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_([context.agent_id, context.other_agent_id])
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_contacts_encrypt_lookup_and_never_merge_principals(
    contact_crypto_keys,
    commercial_context: CommercialContext,
) -> None:
    service = ContactService(crypto=ContactCrypto())
    context = commercial_context
    raw_email = "Oscar.Vargas@example.com"

    async with AsyncSessionLocal() as db:
        created = await service.ensure_contact(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            company_name="SaltaCode",
        )
        repeated = await service.ensure_contact(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            company_name="SaltaCode",
        )
        point = await service.add_contact_point(
            db,
            agent_id=context.agent_id,
            contact_id=created.contact.id,
            kind="email",
            value=raw_email,
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
        )
        repeated_point = await service.add_contact_point(
            db,
            agent_id=context.agent_id,
            contact_id=created.contact.id,
            kind="email",
            value=raw_email.casefold(),
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
        )
        other_contact = (
            await service.ensure_contact(
                db,
                agent_id=context.agent_id,
                principal_id=context.other_principal_id,
                source_conversation_id=context.mismatched_conversation_id,
                source_channel_identity_id=context.mismatched_identity_id,
            )
        ).contact
        other_point = await service.add_contact_point(
            db,
            agent_id=context.agent_id,
            contact_id=other_contact.id,
            kind="email",
            value=raw_email,
            source_conversation_id=context.mismatched_conversation_id,
            source_channel_identity_id=context.mismatched_identity_id,
        )
        await db.commit()

        assert created.created is True
        assert repeated.created is False
        assert repeated.contact.id == created.contact.id
        assert created.contact.status == "provisional"
        assert point.created is True
        assert repeated_point.created is False
        assert repeated_point.contact_point.id == point.contact_point.id
        assert other_point.contact_point.contact_id != point.contact_point.contact_id
        assert raw_email.casefold() not in point.contact_point.ciphertext.casefold()
        assert raw_email.casefold() != point.contact_point.masked_value.casefold()
        assert (
            ContactCrypto().decrypt(point.contact_point.ciphertext)
            == raw_email.casefold()
        )

    async with AsyncSessionLocal() as db:
        matches = await service.find_contact_points(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            kind="email",
            value=raw_email,
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
        )
        assert [match.id for match in matches] == [point.contact_point.id]

        with pytest.raises(ContactSourceMismatchError):
            await service.add_contact_point(
                db,
                agent_id=context.other_agent_id,
                contact_id=created.contact.id,
                kind="phone",
                value="+5493871234567",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
            )

        with pytest.raises(ContactSourceMismatchError):
            await service.add_contact_point(
                db,
                agent_id=context.agent_id,
                contact_id=created.contact.id,
                kind="phone",
                value="+5493871234567",
                source_conversation_id=context.mismatched_conversation_id,
                source_channel_identity_id=context.mismatched_identity_id,
            )


@pytest.mark.asyncio
async def test_consent_is_idempotent_revocable_expirable_and_purpose_specific(
    contact_crypto_keys,
    commercial_context: CommercialContext,
) -> None:
    contacts = ContactService(crypto=ContactCrypto())
    consents = ConsentService()
    context = commercial_context
    occurred_at = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        transcript_only = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            purpose=ConsentPurpose.CONVERSATION_STORAGE,
        )
        assert transcript_only.granted is False
        assert transcript_only.record is None

        pre_contact = await consents.record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            purpose=ConsentPurpose.CONVERSATION_STORAGE,
            action=ConsentAction.GRANT,
            policy_version="transcript-v2",
            channel="web",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="storage-request-1",
            idempotency_key="storage-consent-1",
            occurred_at=occurred_at,
        )
        assert pre_contact.record.contact_id is None
        stored_before_contact = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            purpose=ConsentPurpose.CONVERSATION_STORAGE,
            at=occurred_at + timedelta(seconds=1),
        )
        assert stored_before_contact.granted is True

        contact = (
            await contacts.ensure_contact(
                db,
                agent_id=context.agent_id,
                principal_id=context.principal_id,
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
            )
        ).contact
        point = (
            await contacts.add_contact_point(
                db,
                agent_id=context.agent_id,
                contact_id=contact.id,
                kind="email",
                value="lead@example.com",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
            )
        ).contact_point
        db.add(
            ConsentRecord(
                principal_id=context.principal_id,
                contact_id=contact.id,
                contact_point_id=point.id,
                agent_id=context.agent_id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                action=ConsentAction.GRANT,
                policy_version="legacy-commercial-v1",
                channel="web",
                locale="es-AR",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
                correlation_id="legacy-targetless-consent",
                idempotency_key="legacy-targetless-consent",
                command_hash="f" * 64,
                occurred_at=occurred_at,
            )
        )
        await db.flush()

        commercial_only = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            source_conversation_id=context.conversation_id,
            target_channel="email",
        )
        assert commercial_only.granted is False
        assert commercial_only.record is None

        granted = await consents.record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=contact.id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.GRANT,
            policy_version="commercial-v1",
            channel="web",
            target_channel="email",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="request-1",
            idempotency_key="consent-1",
            occurred_at=occurred_at,
        )
        repeated = await consents.record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=contact.id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.GRANT,
            policy_version="commercial-v1",
            channel="web",
            target_channel="email",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="retry-request-2",
            idempotency_key="consent-1",
            occurred_at=occurred_at + timedelta(minutes=1),
        )
        assert granted.created is True
        assert repeated.created is False
        assert repeated.record.id == granted.record.id

        with pytest.raises(ConsentIdempotencyConflictError):
            await consents.record(
                db,
                agent_id=context.agent_id,
                principal_id=context.principal_id,
                contact_id=contact.id,
                contact_point_id=point.id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                action=ConsentAction.REVOKE,
                policy_version="commercial-v1",
                channel="web",
                target_channel="email",
                locale="es-AR",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
                correlation_id="request-3",
                idempotency_key="consent-1",
                occurred_at=occurred_at + timedelta(minutes=2),
            )

        effective = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            source_conversation_id=context.conversation_id,
            target_channel="email",
            at=occurred_at + timedelta(seconds=1),
        )
        assert effective.granted is True
        wrong_target = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            source_conversation_id=context.conversation_id,
            target_channel="whatsapp",
            at=occurred_at + timedelta(seconds=1),
        )
        assert wrong_target.granted is False
        assert wrong_target.record is None

        await consents.record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=contact.id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.REVOKE,
            policy_version="commercial-v1",
            channel="web",
            target_channel="email",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="request-4",
            idempotency_key="consent-2",
            occurred_at=occurred_at + timedelta(minutes=3),
        )
        await consents.record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=contact.id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.MARKETING,
            action=ConsentAction.GRANT,
            policy_version="marketing-v1",
            channel="web",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="request-5",
            idempotency_key="consent-3",
            occurred_at=occurred_at,
            expires_at=occurred_at + timedelta(minutes=2),
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        revoked = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            source_conversation_id=context.conversation_id,
            target_channel="email",
            at=occurred_at + timedelta(minutes=4),
        )
        expired = await consents.effective(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_point_id=point.id,
            purpose=ConsentPurpose.MARKETING,
            at=occurred_at + timedelta(minutes=4),
        )
        assert revoked.granted is False
        assert revoked.record is not None
        assert revoked.record.action == ConsentAction.REVOKE
        assert expired.granted is False
        assert expired.record is not None

        with pytest.raises(ContactNotFoundError):
            await consents.effective(
                db,
                agent_id=context.other_agent_id,
                principal_id=context.principal_id,
                contact_point_id=point.id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                source_conversation_id=context.conversation_id,
                target_channel="email",
            )
        with pytest.raises(ContactSourceMismatchError):
            await consents.record(
                db,
                agent_id=context.agent_id,
                principal_id=context.principal_id,
                contact_id=contact.id,
                contact_point_id=point.id,
                purpose=ConsentPurpose.QUOTE_DELIVERY,
                action=ConsentAction.GRANT,
                policy_version="quote-v1",
                channel="web",
                locale="es-AR",
                source_conversation_id=context.mismatched_conversation_id,
                source_channel_identity_id=context.mismatched_identity_id,
                correlation_id="request-6",
                idempotency_key="consent-4",
            )
        with pytest.raises(ConsentSubjectMismatchError):
            await consents.record(
                db,
                agent_id=context.agent_id,
                principal_id=context.other_principal_id,
                contact_id=contact.id,
                purpose=ConsentPurpose.QUOTE_DELIVERY,
                action=ConsentAction.GRANT,
                policy_version="quote-v1",
                channel="web",
                locale="es-AR",
                source_conversation_id=context.mismatched_conversation_id,
                source_channel_identity_id=context.mismatched_identity_id,
                correlation_id="request-7",
                idempotency_key="consent-5",
            )


@pytest.mark.asyncio
async def test_target_scoped_effective_waits_for_grant_and_revoke(
    contact_crypto_keys,
    commercial_context: CommercialContext,
) -> None:
    context = commercial_context
    contacts = ContactService(crypto=ContactCrypto())
    consents = ConsentService()
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        contact = (
            await contacts.ensure_contact(
                db,
                agent_id=context.agent_id,
                principal_id=context.principal_id,
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
            )
        ).contact
        point = (
            await contacts.add_contact_point(
                db,
                agent_id=context.agent_id,
                contact_id=contact.id,
                kind="email",
                value="serialized-consent@example.com",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
            )
        ).contact_point
        await db.commit()
        contact_id = contact.id
        point_id = point.id

    grant_db = AsyncSessionLocal()
    observer_db = AsyncSessionLocal()
    try:
        await consents.record(
            grant_db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=contact_id,
            contact_point_id=point_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.GRANT,
            policy_version="commercial-v1",
            channel="web",
            target_channel="email",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="serialized-grant",
            idempotency_key="serialized-grant",
            occurred_at=now,
        )

        async def read_effective():
            result = await consents.effective(
                observer_db,
                agent_id=context.agent_id,
                principal_id=context.principal_id,
                contact_point_id=point_id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                source_conversation_id=context.conversation_id,
                target_channel="email",
                at=now + timedelta(seconds=1),
            )
            await observer_db.commit()
            return result

        competing_read = asyncio.create_task(read_effective())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(competing_read), timeout=0.05)
        await grant_db.commit()
        granted = await asyncio.wait_for(competing_read, timeout=2)
        assert granted.granted is True
    finally:
        await grant_db.close()
        await observer_db.close()

    revoke_db = AsyncSessionLocal()
    final_db = AsyncSessionLocal()
    try:
        await consents.record(
            revoke_db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=contact_id,
            contact_point_id=point_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.REVOKE,
            policy_version="commercial-v1",
            channel="web",
            target_channel="email",
            locale="es-AR",
            source_conversation_id=context.conversation_id,
            source_channel_identity_id=context.identity_id,
            correlation_id="serialized-revoke",
            idempotency_key="serialized-revoke",
            occurred_at=now + timedelta(seconds=2),
        )
        competing_read = asyncio.create_task(
            consents.effective(
                final_db,
                agent_id=context.agent_id,
                principal_id=context.principal_id,
                contact_point_id=point_id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
                source_conversation_id=context.conversation_id,
                target_channel="email",
                at=now + timedelta(seconds=3),
            )
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(competing_read), timeout=0.05)
        await revoke_db.commit()
        revoked = await asyncio.wait_for(competing_read, timeout=2)
        assert revoked.granted is False
        assert revoked.record is not None
        assert revoked.record.action == ConsentAction.REVOKE
    finally:
        await revoke_db.close()
        await final_db.close()


@pytest.mark.asyncio
async def test_database_rejects_invalid_contact_and_consent_rows(
    commercial_context: CommercialContext,
) -> None:
    context = commercial_context
    async with AsyncSessionLocal() as db:
        db.add(
            Contact(
                principal_id=context.principal_id,
                created_by_agent_id=context.agent_id,
                status="deleted",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async with AsyncSessionLocal() as db:
        contact = Contact(
            principal_id=context.principal_id,
            created_by_agent_id=context.agent_id,
        )
        db.add(contact)
        await db.flush()
        db.add(
            ContactPoint(
                contact_id=contact.id,
                kind="postal",
                ciphertext="encrypted-value-that-is-long-enough-to-pass-the-length-check",
                lookup_hmac="a" * 64,
                masked_value="masked",
                verification_status="unverified",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    async with AsyncSessionLocal() as db:
        contact = Contact(
            principal_id=context.principal_id,
            created_by_agent_id=context.agent_id,
        )
        db.add(contact)
        await db.flush()
        occurred_at = datetime.now(UTC)
        db.add(
            ConsentRecord(
                principal_id=context.principal_id,
                contact_id=contact.id,
                agent_id=context.agent_id,
                purpose=ConsentPurpose.MARKETING,
                action=ConsentAction.REVOKE,
                policy_version="marketing-v1",
                channel="web",
                locale="es-AR",
                source_conversation_id=context.conversation_id,
                source_channel_identity_id=context.identity_id,
                correlation_id="constraint-test",
                idempotency_key="constraint-test",
                command_hash="a" * 64,
                occurred_at=occurred_at,
                expires_at=occurred_at + timedelta(days=1),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


def _agent(*, slug: str) -> AgentProfile:
    return AgentProfile(
        name=slug,
        slug=slug,
        is_active=True,
        is_public=False,
        prompt_identity="identity",
        prompt_domain="domain",
        prompt_guardrails="guardrails",
        unauthorized_message="unauthorized",
        error_message="error",
    )
