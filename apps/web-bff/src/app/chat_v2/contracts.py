"""Validated browser and private Agent Platform contracts for web chat v2."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

_PRIVATE_PAYLOAD_KEYS = frozenset(
    {
        "actor_admin_id",
        "agent_id",
        "assigned_admin_id",
        "conversation_id",
        "principal_id",
        "route_key",
        "tool_arguments",
        "tool_call_id",
        "tool_name",
    }
)


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


ChatContent = Annotated[str, StringConstraints(min_length=1, max_length=16_000)]
PrivacyVersion = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
CommercialTitle = Annotated[str, StringConstraints(min_length=1, max_length=200)]
CommercialSummary = Annotated[str, StringConstraints(min_length=1, max_length=8_000)]
ContactValue = Annotated[str, StringConstraints(min_length=3, max_length=320)]
_EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")


class BrowserMessageRequest(StrictContract):
    client_message_id: UUID
    message: ChatContent
    locale: Literal["es-AR", "es", "en"] = "es-AR"
    transcript_consent: Literal[True]
    privacy_version: PrivacyVersion


class BrowserResetRequest(StrictContract):
    transcript_consent: Literal[True]
    privacy_version: PrivacyVersion


class BrowserCommercialContactRequest(StrictContract):
    client_request_id: UUID
    locale: Literal["es-AR", "es", "en"] = "es-AR"
    title: CommercialTitle
    summary: CommercialSummary | None = None
    contact_kind: Literal["email", "phone"]
    contact_value: ContactValue
    preferred_delivery_channel: Literal["email", "whatsapp"]
    quote_delivery_consent: Literal[True]
    commercial_follow_up_consent: bool
    privacy_version: PrivacyVersion

    @model_validator(mode="after")
    def validate_contact_and_delivery_channel(self) -> BrowserCommercialContactRequest:
        expected_channel = "email" if self.contact_kind == "email" else "whatsapp"
        if self.preferred_delivery_channel != expected_channel:
            raise ValueError("contact kind does not match preferred delivery channel")
        if self.contact_kind == "email" and (
            ".." in self.contact_value or not _EMAIL_PATTERN.fullmatch(self.contact_value)
        ):
            raise ValueError("contact value must be a valid email address")
        if self.contact_kind == "phone" and not _PHONE_PATTERN.fullmatch(self.contact_value):
            raise ValueError("contact value must be an E.164 phone number")
        return self


class TranscriptConsent(StrictContract):
    granted: Literal[True]
    version: PrivacyVersion


class PrivateMessageRequest(StrictContract):
    session_id: UUID
    client_message_id: UUID
    route_key: str
    content: ChatContent
    locale: Literal["es-AR", "es", "en"]
    consent: TranscriptConsent


class PrivateCommercialContactRequest(StrictContract):
    session_id: UUID
    route_key: str
    client_request_id: UUID
    locale: Literal["es-AR", "es", "en"]
    title: CommercialTitle
    summary: CommercialSummary | None = None
    contact_kind: Literal["email", "phone"]
    contact_value: ContactValue
    preferred_delivery_channel: Literal["email", "whatsapp"]
    quote_delivery_consent: Literal[True]
    commercial_follow_up_consent: bool
    policy_version: PrivacyVersion


class CommercialContactAccepted(StrictContract):
    opportunity_id: UUID
    target_agent_id: UUID
    status: Literal["accepted"]


class MessageAccepted(StrictContract):
    client_message_id: UUID
    message_id: UUID
    status: Literal["accepted"]
    event_cursor: int = Field(ge=1)
    duplicate: bool


class HistoryMessage(StrictContract):
    message_id: UUID
    client_message_id: str = Field(min_length=1, max_length=255)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=16_000)
    status: str = Field(min_length=1, max_length=30)
    created_at: datetime


class HistoryResponse(StrictContract):
    status: Literal["active", "closed"]
    control_mode: Literal["automated", "paused", "human", "closed"]
    latest_event_id: int = Field(ge=0)
    messages: list[HistoryMessage]


class ConversationEvent(StrictContract):
    schema_version: Literal["2"]
    cursor: int = Field(ge=1)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9.]{2,99}$")
    occurred_at: datetime
    payload: dict[str, object]

    @field_validator("payload")
    @classmethod
    def reject_private_payload_fields(cls, value: dict[str, object]) -> dict[str, object]:
        if _contains_private_key(value):
            raise ValueError("event payload contains private fields")
        return value


class EventsResponse(StrictContract):
    after: int = Field(ge=0)
    next_cursor: int = Field(ge=0)
    has_more: bool
    events: list[ConversationEvent]


class PrivateResetRequest(StrictContract):
    session_id: UUID
    next_session_id: UUID
    route_key: str
    consent: TranscriptConsent


class ResetResponse(StrictContract):
    status: Literal["active"]
    latest_event_id: int = Field(ge=0)


class StreamFailure(StrictContract):
    schema_version: Literal["2"] = "2"
    code: Literal["chat_temporarily_unavailable"] = "chat_temporarily_unavailable"
    retryable: Literal[True] = True


class StreamDone(StrictContract):
    schema_version: Literal["2"] = "2"
    outcome: Literal["failed"] = "failed"


def _contains_private_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in _PRIVATE_PAYLOAD_KEYS or _contains_private_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_private_key(item) for item in value)
    return False
