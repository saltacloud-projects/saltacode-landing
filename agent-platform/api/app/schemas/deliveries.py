"""Read-only administration contracts for outbound delivery review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"
    CANCELLED = "cancelled"


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
