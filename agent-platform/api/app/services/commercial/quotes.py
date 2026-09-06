"""Caller-transaction-owned quote request and authority-evidence policy."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.quote import QuoteRequest, QuoteVersion
from app.services.commercial.opportunities import (
    OpportunityNotFoundError,
    OpportunityService,
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_MAX_REQUIREMENTS_BYTES = 65_536


class QuoteRequestStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    REVIEW_REQUIRED = "review_required"
    ISSUED = "issued"
    CANCELLED = "cancelled"


class QuoteServiceError(Exception):
    """Base failure for quote request and evidence policy."""


class QuoteRequestNotFoundError(QuoteServiceError):
    """The quote request is absent from the owned opportunity."""


class QuoteVersionConflictError(QuoteServiceError):
    """The caller acted on an obsolete quote request state."""


class QuoteIdempotencyConflictError(QuoteServiceError):
    """An idempotency key was reused for different quote meaning."""


class InvalidQuoteCommandError(QuoteServiceError):
    """A quote command is incomplete or lacks authority evidence."""


@dataclass(frozen=True, slots=True)
class QuoteRequestResult:
    request: QuoteRequest
    created: bool


@dataclass(frozen=True, slots=True)
class QuoteVersionResult:
    request: QuoteRequest
    version: QuoteVersion
    created: bool


class QuoteService:
    """Persist requests safely and issue only externally authoritative versions."""

    def __init__(self, *, opportunities: OpportunityService | None = None) -> None:
        self._opportunities = opportunities or OpportunityService()

    async def request(
        self,
        db: AsyncSession,
        *,
        opportunity_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        requirements: dict,
        correlation_id: str,
        idempotency_key: str,
        status: QuoteRequestStatus | str = QuoteRequestStatus.UNAVAILABLE,
        failure_code: str = "quote_provider_unavailable",
    ) -> QuoteRequestResult:
        normalized_status = _enum_value(status)
        if normalized_status not in {
            QuoteRequestStatus.UNAVAILABLE,
            QuoteRequestStatus.REVIEW_REQUIRED,
        }:
            raise InvalidQuoteCommandError(
                "a quote request starts unavailable or review_required"
            )
        normalized_requirements = _requirements(requirements)
        normalized_failure = _safe_code(failure_code)
        correlation = _required_text(correlation_id, "correlation_id", 120)
        key = _required_text(idempotency_key, "idempotency_key", 220)
        opportunity = await self._opportunities.lock_owned(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=actor_agent_id,
            actor_operator_id=actor_operator_id,
        )
        _assert_opportunity_open(opportunity)
        await _assert_contact_available(db, opportunity.contact_id)
        command_hash = _command_hash(
            {
                "failure_code": normalized_failure,
                "opportunity_id": str(opportunity.id),
                "requirements": normalized_requirements,
                "status": normalized_status.value,
            }
        )
        existing = (
            await db.execute(
                select(QuoteRequest).where(
                    QuoteRequest.opportunity_id == opportunity.id,
                    QuoteRequest.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _assert_hash(existing.command_hash, command_hash)
            return QuoteRequestResult(request=existing, created=False)

        request = QuoteRequest(
            id=uuid.uuid5(opportunity.id, f"quote-request:{key}"),
            opportunity_id=opportunity.id,
            requested_by_agent_id=actor_agent_id,
            requested_by_operator_id=actor_operator_id,
            status=normalized_status.value,
            state_version=0,
            requirements_json=normalized_requirements,
            failure_code=normalized_failure,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
        )
        db.add(request)
        await db.flush()
        return QuoteRequestResult(request=request, created=True)

    async def issue_authoritative_version(
        self,
        db: AsyncSession,
        *,
        quote_request_id: uuid.UUID,
        actor_agent_id: uuid.UUID,
        actor_operator_id: uuid.UUID | None,
        expected_version: int,
        authority_name: str,
        authority_version: str,
        external_reference: str,
        content_hash: str,
        issued_at: datetime,
        correlation_id: str,
        idempotency_key: str,
        recorded_at: datetime | None = None,
    ) -> QuoteVersionResult:
        authority = _required_text(authority_name, "authority_name", 120)
        authority_release = _required_text(
            authority_version,
            "authority_version",
            80,
        )
        external_ref = _required_text(
            external_reference,
            "external_reference",
            255,
        )
        normalized_hash = content_hash.strip()
        if not _SHA256_HEX.fullmatch(normalized_hash):
            raise InvalidQuoteCommandError("content_hash must be lowercase SHA-256 hex")
        normalized_issued_at = _aware_utc(issued_at, "issued_at")
        normalized_recorded_at = _aware_utc(
            recorded_at or datetime.now(UTC),
            "recorded_at",
        )
        if normalized_issued_at > normalized_recorded_at:
            raise InvalidQuoteCommandError("issued_at cannot be in the future")
        correlation = _required_text(correlation_id, "correlation_id", 120)
        key = _required_text(idempotency_key, "idempotency_key", 220)
        if expected_version < 0:
            raise QuoteVersionConflictError("invalid quote request state version")
        command_hash = _command_hash(
            {
                "authority_name": authority,
                "authority_version": authority_release,
                "content_hash": normalized_hash,
                "expected_version": expected_version,
                "external_reference": external_ref,
                "issued_at": normalized_issued_at.isoformat(),
                "quote_request_id": str(quote_request_id),
            }
        )
        request = (
            await db.execute(
                select(QuoteRequest)
                .where(QuoteRequest.id == quote_request_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise QuoteRequestNotFoundError("quote request not found")
        try:
            opportunity = await self._opportunities.lock_owned(
                db,
                opportunity_id=request.opportunity_id,
                actor_agent_id=actor_agent_id,
                actor_operator_id=actor_operator_id,
            )
        except OpportunityNotFoundError as exc:
            raise QuoteRequestNotFoundError("quote request not found") from exc
        _assert_opportunity_open(opportunity)
        await _assert_contact_available(db, opportunity.contact_id)

        existing = (
            await db.execute(
                select(QuoteVersion).where(
                    QuoteVersion.quote_request_id == request.id,
                    QuoteVersion.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _assert_hash(existing.command_hash, command_hash)
            return QuoteVersionResult(
                request=request,
                version=existing,
                created=False,
            )
        if request.status == QuoteRequestStatus.CANCELLED:
            raise InvalidQuoteCommandError("a cancelled quote request cannot be issued")
        if request.state_version != expected_version:
            raise QuoteVersionConflictError("quote request state version changed")

        current_max = (
            await db.execute(
                select(func.max(QuoteVersion.version)).where(
                    QuoteVersion.quote_request_id == request.id
                )
            )
        ).scalar_one()
        version_number = (current_max or 0) + 1
        version = QuoteVersion(
            id=uuid.uuid5(request.id, f"quote-version:{key}"),
            quote_request_id=request.id,
            version=version_number,
            status=QuoteRequestStatus.ISSUED,
            authority_name=authority,
            authority_version=authority_release,
            external_reference=external_ref,
            content_hash=normalized_hash,
            correlation_id=correlation,
            idempotency_key=key,
            command_hash=command_hash,
            issued_at=normalized_issued_at,
            created_at=normalized_recorded_at,
        )
        request.status = QuoteRequestStatus.ISSUED
        request.failure_code = None
        request.state_version += 1
        db.add(version)
        await db.flush()
        return QuoteVersionResult(request=request, version=version, created=True)


def _requirements(value: dict) -> dict:
    if not isinstance(value, dict):
        raise InvalidQuoteCommandError("requirements must be an object")
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidQuoteCommandError(
            "requirements must be JSON serializable"
        ) from exc
    if len(canonical.encode("utf-8")) > _MAX_REQUIREMENTS_BYTES:
        raise InvalidQuoteCommandError("requirements payload is too large")
    return json.loads(canonical)


def _enum_value(value: QuoteRequestStatus | str) -> QuoteRequestStatus:
    try:
        return QuoteRequestStatus(value)
    except (TypeError, ValueError) as exc:
        raise InvalidQuoteCommandError("invalid quote request status") from exc


def _safe_code(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_CODE.fullmatch(normalized):
        raise InvalidQuoteCommandError("invalid quote failure code")
    return normalized


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise InvalidQuoteCommandError(f"invalid {field}")
    return normalized


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidQuoteCommandError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _command_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_hash(actual: str, expected: str) -> None:
    if not _SHA256_HEX.fullmatch(actual) or actual != expected:
        raise QuoteIdempotencyConflictError(
            "idempotency key belongs to another quote command"
        )


def _assert_opportunity_open(opportunity: Opportunity) -> None:
    if opportunity.stage in {"won", "lost"}:
        raise InvalidQuoteCommandError("commercial opportunity is closed")


async def _assert_contact_available(
    db: AsyncSession,
    contact_id: uuid.UUID,
) -> None:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.status == "archived":
        raise InvalidQuoteCommandError("commercial contact is unavailable")


quote_service = QuoteService()
