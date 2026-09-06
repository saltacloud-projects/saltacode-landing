"""Fail-closed operator resolution for uncertain outbound delivery outcomes."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.delivery_resolution import (
    DeliveryEvidenceSource,
    DeliveryNotDeliveredReason,
    DeliveryResolutionAction,
)
from app.models.outbound import (
    OutboundDeliveryEvent,
    OutboundDeliveryResolution,
    OutboundMessage,
)


class DeliveryResolutionError(Exception):
    """Base error for privacy-safe uncertainty resolution."""


class DeliveryResolutionNotFoundError(DeliveryResolutionError):
    """The delivery is absent from the requested agent scope."""


class DeliveryResolutionVersionConflictError(DeliveryResolutionError):
    """The caller used an obsolete resolution version."""


class DeliveryResolutionIdempotencyConflictError(DeliveryResolutionError):
    """The idempotency key belongs to another resolution command."""


class InvalidDeliveryResolutionError(DeliveryResolutionError):
    """The requested resolution violates fail-closed delivery policy."""


@dataclass(frozen=True, slots=True)
class DeliveryResolutionResult:
    message: OutboundMessage
    resolution: OutboundDeliveryResolution
    applied: bool


class OutboundDeliveryResolutionService:
    """Resolve uncertainty once without retrying or creating another attempt."""

    async def resolve(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        delivery_id: uuid.UUID,
        admin_id: uuid.UUID,
        action: DeliveryResolutionAction,
        expected_resolution_version: int,
        provider_message_id: str | None,
        evidence_source: DeliveryEvidenceSource | None,
        reason_code: DeliveryNotDeliveredReason | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> DeliveryResolutionResult:
        key = self._required_text(idempotency_key, "idempotency_key", 220)
        correlation = self._required_text(correlation_id, "correlation_id", 120)
        provider_reference = self._normalize_provider_reference(provider_message_id)
        self._validate_evidence(
            action=action,
            provider_message_id=provider_reference,
            evidence_source=evidence_source,
            reason_code=reason_code,
        )
        command_hash = self._command_hash(
            agent_id=agent_id,
            delivery_id=delivery_id,
            admin_id=admin_id,
            action=action,
            expected_resolution_version=expected_resolution_version,
            provider_message_id=provider_reference,
            evidence_source=evidence_source,
            reason_code=reason_code,
        )
        message = (
            await db.execute(
                select(OutboundMessage)
                .where(
                    OutboundMessage.id == delivery_id,
                    OutboundMessage.agent_id == agent_id,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if message is None:
            raise DeliveryResolutionNotFoundError("delivery not found")

        existing = (
            await db.execute(
                select(OutboundDeliveryResolution).where(
                    OutboundDeliveryResolution.outbound_message_id == message.id,
                    OutboundDeliveryResolution.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if not secrets.compare_digest(existing.command_hash, command_hash):
                raise DeliveryResolutionIdempotencyConflictError(
                    "idempotency key belongs to another resolution command"
                )
            return DeliveryResolutionResult(
                message=message,
                resolution=existing,
                applied=False,
            )

        if message.resolution_version != expected_resolution_version:
            raise DeliveryResolutionVersionConflictError(
                "delivery resolution version changed"
            )
        if message.status != "delivery_unknown":
            raise InvalidDeliveryResolutionError(
                "only an uncertain delivery can be resolved"
            )

        previous_status = message.status
        next_version = message.resolution_version + 1
        resolved_at = datetime.now(UTC)
        if action == DeliveryResolutionAction.CONFIRM_DELIVERED:
            await self._assert_provider_reference_available(
                db,
                message=message,
                provider_message_id=provider_reference,
            )
            message.status = "delivered"
            message.provider_message_id = provider_reference
            message.accepted_at = message.accepted_at or resolved_at
            message.delivered_at = resolved_at
            safe_code = "operator_confirmed_delivery"
        else:
            message.status = "cancelled"
            safe_code = "operator_confirmed_non_delivery"
        message.resolution_version = next_version

        resolution = OutboundDeliveryResolution(
            outbound_message_id=message.id,
            resolution_version=next_version,
            action=action.value,
            provider_message_hash=self._provider_reference_hash(provider_reference),
            provider_message_suffix=(
                provider_reference[-6:] if provider_reference else None
            ),
            evidence_source=(evidence_source.value if evidence_source else None),
            reason_code=reason_code.value if reason_code else None,
            actor_admin_id=admin_id,
            idempotency_key=key,
            command_hash=command_hash,
            correlation_id=correlation,
        )
        db.add(resolution)
        db.add(
            OutboundDeliveryEvent(
                outbound_message_id=message.id,
                attempt_id=None,
                event_type=message.status,
                from_status=previous_status,
                to_status=message.status,
                actor_type="operator",
                actor_id=str(admin_id),
                safe_code=safe_code,
            )
        )
        await db.flush()
        return DeliveryResolutionResult(
            message=message,
            resolution=resolution,
            applied=True,
        )

    @staticmethod
    async def _assert_provider_reference_available(
        db: AsyncSession,
        *,
        message: OutboundMessage,
        provider_message_id: str | None,
    ) -> None:
        duplicate = (
            await db.execute(
                select(OutboundMessage.id).where(
                    OutboundMessage.channel_route_id == message.channel_route_id,
                    OutboundMessage.provider_message_id == provider_message_id,
                    OutboundMessage.id != message.id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise InvalidDeliveryResolutionError(
                "provider reference belongs to another delivery"
            )

    @staticmethod
    def _normalize_provider_reference(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or len(normalized) > 255:
            raise InvalidDeliveryResolutionError("invalid provider message id")
        return normalized

    @staticmethod
    def _provider_reference_hash(value: str | None) -> str | None:
        return hashlib.sha256(value.encode()).hexdigest() if value else None

    @staticmethod
    def _validate_evidence(
        *,
        action: DeliveryResolutionAction,
        provider_message_id: str | None,
        evidence_source: DeliveryEvidenceSource | None,
        reason_code: DeliveryNotDeliveredReason | None,
    ) -> None:
        if action == DeliveryResolutionAction.CONFIRM_DELIVERED:
            if provider_message_id is None or evidence_source is None:
                raise InvalidDeliveryResolutionError(
                    "confirm_delivered requires provider evidence"
                )
            if reason_code is not None:
                raise InvalidDeliveryResolutionError(
                    "confirm_delivered cannot include a non-delivery reason"
                )
            return
        if provider_message_id is not None or evidence_source is not None:
            raise InvalidDeliveryResolutionError(
                "confirm_not_delivered cannot include delivery evidence"
            )
        if reason_code is None:
            raise InvalidDeliveryResolutionError(
                "confirm_not_delivered requires a reason code"
            )

    @staticmethod
    def _required_text(value: str, field: str, max_length: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > max_length:
            raise InvalidDeliveryResolutionError(f"invalid {field}")
        return normalized

    @staticmethod
    def _command_hash(
        *,
        agent_id: uuid.UUID,
        delivery_id: uuid.UUID,
        admin_id: uuid.UUID,
        action: DeliveryResolutionAction,
        expected_resolution_version: int,
        provider_message_id: str | None,
        evidence_source: DeliveryEvidenceSource | None,
        reason_code: DeliveryNotDeliveredReason | None,
    ) -> str:
        payload = {
            "action": action.value,
            "admin_id": str(admin_id),
            "agent_id": str(agent_id),
            "delivery_id": str(delivery_id),
            "evidence_source": evidence_source.value if evidence_source else None,
            "expected_resolution_version": expected_resolution_version,
            "provider_message_id": provider_message_id,
            "reason_code": reason_code.value if reason_code else None,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


outbound_delivery_resolution_service = OutboundDeliveryResolutionService()
