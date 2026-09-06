"""PostgreSQL lifecycle coverage for durable identity-link claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.identity_link_claim import (
    IdentityLinkClaim,
    IdentityLinkClaimEvent,
)
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.services.identity_link_claims import (
    IdentityLinkClaimConflictError,
    IdentityLinkClaimIdempotencyError,
    IdentityLinkClaimNotFoundError,
    IdentityLinkClaimService,
    IdentityLinkClaimVersionConflictError,
    IdentityProofVerificationError,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class IdentityLinkContext:
    agent_id: UUID
    other_agent_id: UUID
    admin_id: UUID
    admin_role_key: str
    source_identity_id: UUID
    target_identity_id: UUID
    foreign_identity_id: UUID
    source_principal_id: UUID
    target_principal_id: UUID
    foreign_principal_id: UUID
    conversation_ids: tuple[UUID, ...]


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def identity_link_context() -> IdentityLinkContext:
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        agent = _agent(f"identity-link-{suffix}")
        other_agent = _agent(f"identity-link-other-{suffix}")
        role = AdminRole(
            key=f"identity-link-{suffix}"[:40],
            name="Identity link test role",
            description=None,
            permissions=["*"],
            is_active=True,
            is_system=False,
        )
        admin = AdminUser(
            email=f"identity-link-{suffix}@example.test",
            hashed_password="not-used",
            name="Identity link test admin",
            role=role.key,
            is_active=True,
            must_change_password=False,
        )
        source_principal = Principal(display_name="Source identity")
        target_principal = Principal(display_name="Target identity")
        foreign_principal = Principal(display_name="Foreign identity")
        db.add_all(
            [
                agent,
                other_agent,
                role,
                admin,
                source_principal,
                target_principal,
                foreign_principal,
            ]
        )
        await db.flush()

        source_identity = ChannelIdentity(
            principal_id=source_principal.id,
            channel="web",
            route_key=f"web-{suffix}",
            external_subject=f"visitor-{suffix}",
        )
        target_identity = ChannelIdentity(
            principal_id=target_principal.id,
            channel="whatsapp",
            route_key=f"whatsapp-{suffix}",
            external_subject=f"phone-{suffix}",
        )
        foreign_identity = ChannelIdentity(
            principal_id=foreign_principal.id,
            channel="web",
            route_key=f"foreign-{suffix}",
            external_subject=f"foreign-{suffix}",
        )
        db.add_all([source_identity, target_identity, foreign_identity])
        await db.flush()

        conversations = [
            ChatConversation(
                agent_id=agent.id,
                principal_id=source_principal.id,
                channel=source_identity.channel,
                route_key=source_identity.route_key,
                external_thread_id=f"source-{suffix}",
            ),
            ChatConversation(
                agent_id=agent.id,
                principal_id=target_principal.id,
                channel=target_identity.channel,
                route_key=target_identity.route_key,
                external_thread_id=f"target-{suffix}",
            ),
            ChatConversation(
                agent_id=other_agent.id,
                principal_id=foreign_principal.id,
                channel=foreign_identity.channel,
                route_key=foreign_identity.route_key,
                external_thread_id=f"foreign-{suffix}",
            ),
        ]
        db.add_all(conversations)
        await db.commit()
        context = IdentityLinkContext(
            agent_id=agent.id,
            other_agent_id=other_agent.id,
            admin_id=admin.id,
            admin_role_key=role.key,
            source_identity_id=source_identity.id,
            target_identity_id=target_identity.id,
            foreign_identity_id=foreign_identity.id,
            source_principal_id=source_principal.id,
            target_principal_id=target_principal.id,
            foreign_principal_id=foreign_principal.id,
            conversation_ids=tuple(conversation.id for conversation in conversations),
        )

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(IdentityLinkClaim).where(
                    IdentityLinkClaim.agent_id.in_(
                        [context.agent_id, context.other_agent_id]
                    )
                )
            )
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id.in_(context.conversation_ids)
                )
            )
            await db.execute(
                delete(ChannelIdentity).where(
                    ChannelIdentity.id.in_(
                        [
                            context.source_identity_id,
                            context.target_identity_id,
                            context.foreign_identity_id,
                        ]
                    )
                )
            )
            await db.execute(
                delete(Principal).where(
                    Principal.id.in_(
                        [
                            context.source_principal_id,
                            context.target_principal_id,
                            context.foreign_principal_id,
                        ]
                    )
                )
            )
            await db.execute(delete(AdminUser).where(AdminUser.id == context.admin_id))
            await db.execute(
                delete(AdminRole).where(AdminRole.key == context.admin_role_key)
            )
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_([context.agent_id, context.other_agent_id])
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_proof_is_one_time_idempotent_and_never_merges_principals(
    identity_link_context: IdentityLinkContext,
) -> None:
    service = IdentityLinkClaimService()
    context = identity_link_context
    issued_at = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        issued = await service.issue(
            db,
            agent_id=context.agent_id,
            source_identity_id=context.source_identity_id,
            target_identity_id=context.target_identity_id,
            actor_admin_id=context.admin_id,
            proof_method="opaque_token",
            proof_ttl_seconds=900,
            evidence_sha256="a" * 64,
            evidence_reference="web:consent:event-1",
            idempotency_key="issue-link-1",
            occurred_at=issued_at,
        )
        assert issued.applied is True
        assert issued.proof_token is not None
        assert len(issued.proof_token) >= 40
        proof_token = issued.proof_token

        duplicate = await service.issue(
            db,
            agent_id=context.agent_id,
            source_identity_id=context.source_identity_id,
            target_identity_id=context.target_identity_id,
            actor_admin_id=context.admin_id,
            proof_method="opaque_token",
            proof_ttl_seconds=900,
            evidence_sha256="a" * 64,
            evidence_reference="web:consent:event-1",
            idempotency_key="issue-link-1",
            occurred_at=issued_at + timedelta(seconds=10),
        )
        assert duplicate.applied is False
        assert duplicate.proof_token is None
        assert duplicate.view.claim.id == issued.view.claim.id

        with pytest.raises(IdentityLinkClaimIdempotencyError):
            await service.issue(
                db,
                agent_id=context.agent_id,
                source_identity_id=context.source_identity_id,
                target_identity_id=context.target_identity_id,
                actor_admin_id=context.admin_id,
                proof_method="opaque_token",
                proof_ttl_seconds=900,
                evidence_sha256="b" * 64,
                evidence_reference="web:consent:event-1",
                idempotency_key="issue-link-1",
                occurred_at=issued_at,
            )

        claim = issued.view.claim
        assert proof_token not in claim.proof_token_hash
        assert proof_token not in claim.issue_command_hash

        with pytest.raises(IdentityProofVerificationError):
            await service.verify(
                db,
                agent_id=context.agent_id,
                claim_id=claim.id,
                actor_admin_id=context.admin_id,
                proof_token="wrong-proof-token-that-is-at-least-forty-characters",
                expected_version=0,
                idempotency_key="verify-wrong-1",
                occurred_at=issued_at + timedelta(seconds=20),
            )

        verified = await service.verify(
            db,
            agent_id=context.agent_id,
            claim_id=claim.id,
            actor_admin_id=context.admin_id,
            proof_token=proof_token,
            expected_version=0,
            idempotency_key="verify-link-1",
            occurred_at=issued_at + timedelta(seconds=30),
        )
        repeated = await service.verify(
            db,
            agent_id=context.agent_id,
            claim_id=claim.id,
            actor_admin_id=context.admin_id,
            proof_token=proof_token,
            expected_version=0,
            idempotency_key="verify-link-1",
            occurred_at=issued_at + timedelta(seconds=40),
        )
        assert verified.applied is True
        assert verified.view.claim.status == "verified"
        assert verified.view.claim.control_version == 1
        assert verified.view.claim.proof_token_hash is None
        assert verified.view.claim.proof_consumed_at is not None
        assert repeated.applied is False

        with pytest.raises(IdentityLinkClaimVersionConflictError):
            await service.revoke(
                db,
                agent_id=context.agent_id,
                claim_id=claim.id,
                actor_admin_id=context.admin_id,
                expected_version=0,
                idempotency_key="revoke-stale-1",
                occurred_at=issued_at + timedelta(seconds=50),
            )

        revoked = await service.revoke(
            db,
            agent_id=context.agent_id,
            claim_id=claim.id,
            actor_admin_id=context.admin_id,
            expected_version=1,
            idempotency_key="revoke-link-1",
            occurred_at=issued_at + timedelta(seconds=60),
        )
        await db.commit()

        assert revoked.view.claim.status == "revoked"
        assert revoked.view.claim.control_version == 2
        source = await db.get(ChannelIdentity, context.source_identity_id)
        target = await db.get(ChannelIdentity, context.target_identity_id)
        assert source.principal_id == context.source_principal_id
        assert target.principal_id == context.target_principal_id
        assert source.principal_id != target.principal_id
        events = list(
            (
                await db.execute(
                    select(IdentityLinkClaimEvent)
                    .where(IdentityLinkClaimEvent.claim_id == claim.id)
                    .order_by(IdentityLinkClaimEvent.control_version)
                )
            )
            .scalars()
            .all()
        )
        assert [event.event_type for event in events] == [
            "issued",
            "verified",
            "revoked",
        ]


@pytest.mark.asyncio
async def test_reject_expire_and_agent_scope_are_enforced(
    identity_link_context: IdentityLinkContext,
) -> None:
    service = IdentityLinkClaimService()
    context = identity_link_context
    issued_at = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        with pytest.raises(IdentityLinkClaimNotFoundError):
            await service.issue(
                db,
                agent_id=context.agent_id,
                source_identity_id=context.source_identity_id,
                target_identity_id=context.foreign_identity_id,
                actor_admin_id=context.admin_id,
                proof_method="opaque_token",
                proof_ttl_seconds=60,
                evidence_sha256=None,
                evidence_reference=None,
                idempotency_key="foreign-link-1",
                occurred_at=issued_at,
            )

        rejected_claim = await service.issue(
            db,
            agent_id=context.agent_id,
            source_identity_id=context.source_identity_id,
            target_identity_id=context.target_identity_id,
            actor_admin_id=context.admin_id,
            proof_method="opaque_token",
            proof_ttl_seconds=60,
            evidence_sha256=None,
            evidence_reference="operator:review:1",
            idempotency_key="issue-reject-1",
            occurred_at=issued_at,
        )
        rejected = await service.reject(
            db,
            agent_id=context.agent_id,
            claim_id=rejected_claim.view.claim.id,
            actor_admin_id=context.admin_id,
            expected_version=0,
            idempotency_key="reject-link-1",
            occurred_at=issued_at + timedelta(seconds=10),
        )
        assert rejected.view.claim.status == "rejected"
        assert rejected.view.claim.proof_token_hash is None

        expiring_claim = await service.issue(
            db,
            agent_id=context.agent_id,
            source_identity_id=context.source_identity_id,
            target_identity_id=context.target_identity_id,
            actor_admin_id=context.admin_id,
            proof_method="opaque_token",
            proof_ttl_seconds=60,
            evidence_sha256=None,
            evidence_reference="operator:review:2",
            idempotency_key="issue-expire-1",
            occurred_at=issued_at,
        )
        with pytest.raises(
            IdentityLinkClaimConflictError,
            match="has not expired",
        ):
            await service.expire(
                db,
                agent_id=context.agent_id,
                claim_id=expiring_claim.view.claim.id,
                actor_admin_id=context.admin_id,
                expected_version=0,
                idempotency_key="expire-link-1",
                occurred_at=issued_at + timedelta(seconds=59),
            )
        expired = await service.expire(
            db,
            agent_id=context.agent_id,
            claim_id=expiring_claim.view.claim.id,
            actor_admin_id=context.admin_id,
            expected_version=0,
            idempotency_key="expire-link-1",
            occurred_at=issued_at + timedelta(seconds=61),
        )
        await db.commit()

        assert expired.view.claim.status == "expired"
        assert expired.view.claim.expired_at is not None
        assert expired.view.claim.proof_token_hash is None


def _agent(slug: str) -> AgentProfile:
    return AgentProfile(
        name=f"Identity link {slug}",
        slug=slug,
        version=1,
        is_active=True,
        is_public=False,
        retention_days=30,
        description=None,
        prompt_identity="Test identity",
        prompt_domain="Test domain",
        prompt_guardrails="Test guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
        created_by="integration-test",
    )
