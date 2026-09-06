"""Administration contracts for outbound delivery review and resolution."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.delivery_resolution import (
    DeliveryEvidenceSource,
    DeliveryNotDeliveredReason,
    DeliveryResolutionAction,
)


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"
    CANCELLED = "cancelled"


class DeliveryResolutionRequest(BaseModel):
    action: DeliveryResolutionAction
    expected_resolution_version: int = Field(ge=0)
    provider_message_id: str | None = Field(default=None, min_length=1, max_length=255)
    evidence_source: DeliveryEvidenceSource | None = None
    reason_code: DeliveryNotDeliveredReason | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> DeliveryResolutionRequest:
        if self.action == DeliveryResolutionAction.CONFIRM_DELIVERED:
            if self.provider_message_id is None or self.evidence_source is None:
                raise ValueError("confirm_delivered requires provider evidence")
            if self.reason_code is not None:
                raise ValueError(
                    "confirm_delivered does not accept a non-delivery reason"
                )
            return self
        if self.provider_message_id is not None or self.evidence_source is not None:
            raise ValueError("confirm_not_delivered does not accept delivery evidence")
        if self.reason_code is None:
            raise ValueError("confirm_not_delivered requires a reason code")
        return self


class DeliverySummaryOut(BaseModel):
    id: UUID
    conversation_id: UUID
    channel: str
    status: DeliveryStatus
    kind: str
    sender_type: str
    sequence: int
    correlation_id: str
    provider_reference: str | None
    attempt_count: int
    latest_safe_code: str | None
    is_fifo_blocking: bool
    blocked_message_count: int
    resolution_version: int
    created_at: datetime
    updated_at: datetime


class DeliveryPageOut(BaseModel):
    items: list[DeliverySummaryOut]
    total: int
    limit: int
    offset: int


class DeliveryAttemptOut(BaseModel):
    id: UUID
    attempt_number: int
    control_version: int
    created_at: datetime


class DeliveryEventOut(BaseModel):
    id: UUID
    attempt_id: UUID | None
    event_type: str
    from_status: str | None
    to_status: str
    actor_type: str
    safe_code: str | None
    created_at: datetime


class DeliveryResolutionOut(BaseModel):
    resolution_version: int
    action: DeliveryResolutionAction
    provider_reference: str | None
    evidence_source: DeliveryEvidenceSource | None
    reason_code: DeliveryNotDeliveredReason | None
    has_actor_admin: bool
    created_at: datetime


class DeliveryDetailOut(DeliverySummaryOut):
    channel_route_id: UUID
    channel_connection_id: UUID | None
    adapter_key: str | None
    route_version: int | None
    connection_version: int | None
    chat_message_id: UUID | None
    control_version: int
    accepted_at: datetime | None
    delivered_at: datetime | None
    attempts: list[DeliveryAttemptOut]
    events: list[DeliveryEventOut]
    resolution: DeliveryResolutionOut | None


class DeliveryResolutionMutationOut(BaseModel):
    id: UUID
    status: Literal["delivered", "cancelled"]
    resolution_version: int
    action: DeliveryResolutionAction
    applied: bool
