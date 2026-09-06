"""Versioned channel-neutral contracts for authenticated inbound messages."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ROUTE_KEY_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,119}$"
CHANNEL_PATTERN = r"^[a-z][a-z0-9_-]{0,39}$"

ProviderIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]


class InboundContentType(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InboundRouteContext(FrozenContract):
    route_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=ROUTE_KEY_PATTERN,
    )
    channel_route_id: UUID
    channel_connection_id: UUID


class InboundReplyContext(FrozenContract):
    """Minimal provider reference; quoted content never crosses this boundary."""

    provider_message_id: ProviderIdentifier


class InboundMessageEnvelope(FrozenContract):
    """Immutable message accepted from one authenticated persisted route."""

    schema_version: Literal["1"] = "1"
    correlation_id: UUID
    channel: str = Field(
        min_length=1,
        max_length=40,
        pattern=CHANNEL_PATTERN,
    )
    route: InboundRouteContext
    provider_message_id: ProviderIdentifier
    provider_thread_id: ProviderIdentifier
    provider_sender_id: ProviderIdentifier
    content: str = Field(max_length=16_000)
    content_type: InboundContentType
    timestamp: datetime
    reply_context: InboundReplyContext | None = None
    provider_media_id: ProviderIdentifier | None = None
    interaction_id: ProviderIdentifier | None = None

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("inbound timestamp must include a timezone")
        return value.astimezone(timezone.utc)
