"""Agent-scoped identity proof lifecycle without principal mutation."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_link_claim import (
    IdentityLinkClaim,
    IdentityLinkClaimEvent,
)
from app.models.platform import ChannelIdentity, ChatConversation


class IdentityLinkStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


class IdentityLinkClaimError(Exception):
    """Base failure for identity-link claim policy."""


class IdentityLinkClaimNotFoundError(IdentityLinkClaimError):
    """The claim or identity is absent from the requested agent scope."""


class IdentityLinkClaimValidationError(IdentityLinkClaimError):
    """The requested identity assertion violates a domain invariant."""


class IdentityLinkClaimConflictError(IdentityLinkClaimError):
    """The requested transition conflicts with current durable state."""


class IdentityLinkClaimVersionConflictError(IdentityLinkClaimConflictError):
    """The caller acted on an obsolete claim version."""


class IdentityLinkClaimIdempotencyError(IdentityLinkClaimConflictError):
    """An idempotency key was reused for another command."""


class IdentityProofVerificationError(IdentityLinkClaimConflictError):
    """The supplied opaque proof cannot verify the claim."""


@dataclass(frozen=True, slots=True)
class IdentityLinkClaimView:
    claim: IdentityLinkClaim
    source_identity: ChannelIdentity
    target_identity: ChannelIdentity


@dataclass(frozen=True, slots=True)
class IdentityLinkClaimResult:
    view: IdentityLinkClaimView
    proof_token: str | None
    applied: bool


class IdentityLinkClaimService:
    """Issue and resolve one-time identity proofs inside one agent scope."""

    async def list_claims(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        status: IdentityLinkStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IdentityLinkClaimView]:
        statement = select(IdentityLinkClaim).where(
            IdentityLinkClaim.agent_id == agent_id
        )
        if status is not None:
            statement = statement.where(
                IdentityLinkClaim.status == self._status(status).value
            )
        claims = list(
            (
                await db.execute(
                    statement.order_by(
                        IdentityLinkClaim.updated_at.desc(),
                        IdentityLinkClaim.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [await self._view(db, claim) for claim in claims]

    async def get_claim(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
    ) -> IdentityLinkClaimView:
        claim = await self._load_claim(db, agent_id=agent_id, claim_id=claim_id)
        return await self._view(db, claim)

    async def issue(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        source_identity_id: uuid.UUID,
        target_identity_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        proof_method: str,
        proof_ttl_seconds: int,
        evidence_sha256: str | None,
        evidence_reference: str | None,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> IdentityLinkClaimResult:
        key = self._required_text(idempotency_key, "idempotency_key", 220)
        method = self._required_text(proof_method, "proof_method", 40)
        if method != "opaque_token":
            raise IdentityLinkClaimValidationError("unsupported proof_method")
        if not 60 <= proof_ttl_seconds <= 86_400:
            raise IdentityLinkClaimValidationError("invalid proof_ttl_seconds")
        evidence_hash = self._optional_sha256(evidence_sha256)
        evidence_ref = self._optional_reference(evidence_reference)
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": str(actor_admin_id),
                "evidence_reference": evidence_ref,
                "evidence_sha256": evidence_hash,
                "proof_method": method,
                "proof_ttl_seconds": proof_ttl_seconds,
                "source_identity_id": str(source_identity_id),
                "target_identity_id": str(target_identity_id),
            }
        )
        existing = await self._claim_by_issue_key(
            db,
            agent_id=agent_id,
            idempotency_key=key,
        )
        if existing is not None:
            self._assert_command_hash(existing.issue_command_hash, command_hash)
            return IdentityLinkClaimResult(
                view=await self._view(db, existing),
                proof_token=None,
                applied=False,
            )

        source, target = await self._identity_pair(
            db,
            agent_id=agent_id,
            source_identity_id=source_identity_id,
            target_identity_id=target_identity_id,
        )
        if source.principal_id == target.principal_id:
            raise IdentityLinkClaimValidationError(
                "identities already belong to the same principal"
            )

        proof_token = secrets.token_urlsafe(32)
        proof_token_hash = self._proof_digest(proof_token)
        claim_id = uuid.uuid5(agent_id, f"identity-link-claim:{key}")
        inserted_id = (
            await db.execute(
                insert(IdentityLinkClaim)
                .values(
                    id=claim_id,
                    agent_id=agent_id,
                    source_identity_id=source.id,
                    target_identity_id=target.id,
                    source_principal_id=source.principal_id,
                    target_principal_id=target.principal_id,
                    status=IdentityLinkStatus.PENDING.value,
                    proof_method=method,
                    proof_token_hash=proof_token_hash,
                    proof_expires_at=event_time + timedelta(seconds=proof_ttl_seconds),
                    evidence_sha256=evidence_hash,
                    evidence_reference=evidence_ref,
                    created_by_admin_id=actor_admin_id,
                    control_version=0,
                    issue_idempotency_key=key,
                    issue_command_hash=command_hash,
                    created_at=event_time,
                    updated_at=event_time,
                )
                .on_conflict_do_nothing(
                    constraint="uq_identity_link_claim_agent_idempotency"
                )
                .returning(IdentityLinkClaim.id)
            )
        ).scalar_one_or_none()
        if inserted_id is None:
            concurrent = await self._claim_by_issue_key(
                db,
                agent_id=agent_id,
                idempotency_key=key,
            )
            if concurrent is None:
                raise IdentityLinkClaimConflictError(
                    "identity-link claim could not be created"
                )
            self._assert_command_hash(concurrent.issue_command_hash, command_hash)
            return IdentityLinkClaimResult(
                view=await self._view(db, concurrent),
                proof_token=None,
                applied=False,
            )

        claim = await self._load_claim(
            db,
            agent_id=agent_id,
            claim_id=inserted_id,
        )
        db.add(
            IdentityLinkClaimEvent(
                id=uuid.uuid5(claim.id, "event:0"),
                claim_id=claim.id,
                agent_id=agent_id,
                actor_admin_id=actor_admin_id,
                event_type="issued",
                from_status=None,
                to_status=IdentityLinkStatus.PENDING.value,
                control_version=0,
                idempotency_key=key,
                command_hash=command_hash,
                created_at=event_time,
            )
        )
        await db.flush()
        return IdentityLinkClaimResult(
            view=IdentityLinkClaimView(claim, source, target),
            proof_token=proof_token,
            applied=True,
        )

    async def verify(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        proof_token: str,
        expected_version: int,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> IdentityLinkClaimResult:
        token_digest = self._proof_digest(proof_token)
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": str(actor_admin_id),
                "claim_id": str(claim_id),
                "expected_version": expected_version,
                "proof_token_sha256": token_digest,
                "transition": IdentityLinkStatus.VERIFIED.value,
            }
        )
        claim, duplicate = await self._prepare_transition(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            event_type="verified",
        )
        if duplicate:
            return IdentityLinkClaimResult(
                view=await self._view(db, claim),
                proof_token=None,
                applied=False,
            )
        self._assert_version(claim, expected_version)
        if claim.status != IdentityLinkStatus.PENDING.value:
            raise IdentityLinkClaimConflictError("claim is not pending")
        if event_time >= claim.proof_expires_at:
            raise IdentityProofVerificationError("opaque proof has expired")
        if claim.proof_token_hash is None or not secrets.compare_digest(
            claim.proof_token_hash,
            token_digest,
        ):
            raise IdentityProofVerificationError("opaque proof could not be verified")

        claim.status = IdentityLinkStatus.VERIFIED.value
        claim.control_version += 1
        claim.proof_token_hash = None
        claim.proof_consumed_at = event_time
        claim.verified_by_admin_id = actor_admin_id
        claim.verified_at = event_time
        await self._record_transition(
            db,
            claim=claim,
            actor_admin_id=actor_admin_id,
            event_type="verified",
            from_status=IdentityLinkStatus.PENDING.value,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            occurred_at=event_time,
        )
        return IdentityLinkClaimResult(
            view=await self._view(db, claim),
            proof_token=None,
            applied=True,
        )

    async def reject(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> IdentityLinkClaimResult:
        return await self._terminal_transition(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            actor_admin_id=actor_admin_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            target=IdentityLinkStatus.REJECTED,
            allowed_from=IdentityLinkStatus.PENDING,
            timestamp_field="rejected_at",
            clear_proof=True,
            occurred_at=occurred_at,
        )

    async def revoke(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> IdentityLinkClaimResult:
        return await self._terminal_transition(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            actor_admin_id=actor_admin_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            target=IdentityLinkStatus.REVOKED,
            allowed_from=IdentityLinkStatus.VERIFIED,
            timestamp_field="revoked_at",
            clear_proof=False,
            occurred_at=occurred_at,
        )

    async def expire(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> IdentityLinkClaimResult:
        return await self._terminal_transition(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            actor_admin_id=actor_admin_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            target=IdentityLinkStatus.EXPIRED,
            allowed_from=IdentityLinkStatus.PENDING,
            timestamp_field="expired_at",
            clear_proof=True,
            require_due=True,
            occurred_at=occurred_at,
        )

    async def _terminal_transition(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
        target: IdentityLinkStatus,
        allowed_from: IdentityLinkStatus,
        timestamp_field: str,
        clear_proof: bool,
        require_due: bool = False,
        occurred_at: datetime | None = None,
    ) -> IdentityLinkClaimResult:
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": str(actor_admin_id),
                "claim_id": str(claim_id),
                "expected_version": expected_version,
                "transition": target.value,
            }
        )
        claim, duplicate = await self._prepare_transition(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            event_type=target.value,
        )
        if duplicate:
            return IdentityLinkClaimResult(
                view=await self._view(db, claim),
                proof_token=None,
                applied=False,
            )
        self._assert_version(claim, expected_version)
        if claim.status != allowed_from.value:
            raise IdentityLinkClaimConflictError(
                f"claim must be {allowed_from.value} before {target.value}"
            )
        if require_due and event_time < claim.proof_expires_at:
            raise IdentityLinkClaimConflictError("opaque proof has not expired")

        from_status = claim.status
        claim.status = target.value
        claim.control_version += 1
        if clear_proof:
            claim.proof_token_hash = None
        setattr(claim, timestamp_field, event_time)
        await self._record_transition(
            db,
            claim=claim,
            actor_admin_id=actor_admin_id,
            event_type=target.value,
            from_status=from_status,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            occurred_at=event_time,
        )
        return IdentityLinkClaimResult(
            view=await self._view(db, claim),
            proof_token=None,
            applied=True,
        )

    async def _prepare_transition(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        idempotency_key: str,
        command_hash: str,
        event_type: str,
    ) -> tuple[IdentityLinkClaim, bool]:
        key = self._required_text(idempotency_key, "idempotency_key", 220)
        claim = await self._load_claim(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            for_update=True,
        )
        existing = (
            await db.execute(
                select(IdentityLinkClaimEvent).where(
                    IdentityLinkClaimEvent.agent_id == agent_id,
                    IdentityLinkClaimEvent.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            return claim, False
        if existing.claim_id != claim.id or existing.event_type != event_type:
            raise IdentityLinkClaimIdempotencyError(
                "idempotency key belongs to another identity-link command"
            )
        self._assert_command_hash(existing.command_hash, command_hash)
        return claim, True

    async def _record_transition(
        self,
        db: AsyncSession,
        *,
        claim: IdentityLinkClaim,
        actor_admin_id: uuid.UUID,
        event_type: str,
        from_status: str,
        idempotency_key: str,
        command_hash: str,
        occurred_at: datetime,
    ) -> None:
        db.add(
            IdentityLinkClaimEvent(
                id=uuid.uuid5(claim.id, f"event:{claim.control_version}"),
                claim_id=claim.id,
                agent_id=claim.agent_id,
                actor_admin_id=actor_admin_id,
                event_type=event_type,
                from_status=from_status,
                to_status=claim.status,
                control_version=claim.control_version,
                idempotency_key=self._required_text(
                    idempotency_key,
                    "idempotency_key",
                    220,
                ),
                command_hash=command_hash,
                created_at=occurred_at,
            )
        )
        await db.flush()
        await db.refresh(claim)

    async def _identity_pair(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        source_identity_id: uuid.UUID,
        target_identity_id: uuid.UUID,
    ) -> tuple[ChannelIdentity, ChannelIdentity]:
        if source_identity_id == target_identity_id:
            raise IdentityLinkClaimValidationError("identities must be distinct")
        identities = {
            identity.id: identity
            for identity in (
                (
                    await db.execute(
                        select(ChannelIdentity).where(
                            ChannelIdentity.id.in_(
                                [source_identity_id, target_identity_id]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        source = identities.get(source_identity_id)
        target = identities.get(target_identity_id)
        if source is None or target is None:
            raise IdentityLinkClaimNotFoundError("channel identity not found")
        for identity in (source, target):
            visible = (
                await db.execute(
                    select(ChatConversation.id)
                    .where(
                        ChatConversation.agent_id == agent_id,
                        ChatConversation.principal_id == identity.principal_id,
                        ChatConversation.channel == identity.channel,
                        ChatConversation.route_key == identity.route_key,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if visible is None:
                raise IdentityLinkClaimNotFoundError("channel identity not found")
        return source, target

    async def _view(
        self,
        db: AsyncSession,
        claim: IdentityLinkClaim,
    ) -> IdentityLinkClaimView:
        identities = {
            identity.id: identity
            for identity in (
                (
                    await db.execute(
                        select(ChannelIdentity).where(
                            ChannelIdentity.id.in_(
                                [
                                    claim.source_identity_id,
                                    claim.target_identity_id,
                                ]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        source = identities.get(claim.source_identity_id)
        target = identities.get(claim.target_identity_id)
        if source is None or target is None:
            raise IdentityLinkClaimNotFoundError("channel identity not found")
        return IdentityLinkClaimView(claim, source, target)

    async def _load_claim(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        claim_id: uuid.UUID,
        for_update: bool = False,
    ) -> IdentityLinkClaim:
        statement = select(IdentityLinkClaim).where(
            IdentityLinkClaim.id == claim_id,
            IdentityLinkClaim.agent_id == agent_id,
        )
        if for_update:
            statement = statement.with_for_update()
        claim = (await db.execute(statement)).scalar_one_or_none()
        if claim is None:
            raise IdentityLinkClaimNotFoundError("identity-link claim not found")
        return claim

    async def _claim_by_issue_key(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        idempotency_key: str,
    ) -> IdentityLinkClaim | None:
        return (
            await db.execute(
                select(IdentityLinkClaim).where(
                    IdentityLinkClaim.agent_id == agent_id,
                    IdentityLinkClaim.issue_idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    def _proof_digest(proof_token: str) -> str:
        if not isinstance(proof_token, str) or not 40 <= len(proof_token) <= 256:
            raise IdentityProofVerificationError("opaque proof could not be verified")
        return hashlib.sha256(proof_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _command_hash(payload: dict) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _assert_command_hash(actual: str, expected: str) -> None:
        if not secrets.compare_digest(actual, expected):
            raise IdentityLinkClaimIdempotencyError(
                "idempotency key belongs to another identity-link command"
            )

    @staticmethod
    def _required_text(value: str, field: str, max_length: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > max_length:
            raise IdentityLinkClaimValidationError(f"invalid {field}")
        return normalized

    @staticmethod
    def _optional_sha256(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise IdentityLinkClaimValidationError("invalid evidence_sha256")
        return normalized

    @staticmethod
    def _optional_reference(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 200
            or any(character.isspace() or character in "?#" for character in normalized)
        ):
            raise IdentityLinkClaimValidationError("invalid evidence_reference")
        return normalized

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise IdentityLinkClaimValidationError(
                "occurred_at must include a timezone"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _assert_version(claim: IdentityLinkClaim, expected_version: int) -> None:
        if claim.control_version != expected_version:
            raise IdentityLinkClaimVersionConflictError(
                "identity-link claim version changed"
            )

    @staticmethod
    def _status(value: IdentityLinkStatus | str) -> IdentityLinkStatus:
        try:
            return IdentityLinkStatus(value)
        except ValueError as exc:
            raise IdentityLinkClaimValidationError("invalid status") from exc


identity_link_claim_service = IdentityLinkClaimService()
