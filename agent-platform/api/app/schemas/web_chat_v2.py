"""Private v2 contracts for durable web-chat ingress and resumption."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROUTE_KEY_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,119}$"


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebTranscriptConsent(StrictContract):
    granted: bool
    version: str = Field(min_length=1, max_length=80)


class WebMessageRequest(StrictContract):
    session_id: UUID
    client_message_id: UUID
    route_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=ROUTE_KEY_PATTERN,
    )
    content: str = Field(min_length=1, max_length=16_000)
    locale: str = Field(default="es-AR", min_length=2, max_length=35)
    consent: WebTranscriptConsent


class WebMessageAccepted(StrictContract):
    client_message_id: UUID
    message_id: UUID
    status: Literal["accepted"] = "accepted"
    event_cursor: int = Field(ge=1)
    duplicate: bool


class WebHistoryMessage(StrictContract):
    message_id: UUID
    client_message_id: str = Field(min_length=1, max_length=255)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=16_000)
    status: str = Field(min_length=1, max_length=30)
    created_at: datetime


class WebHistoryResponse(StrictContract):
    status: Literal["active", "closed"]
    control_mode: Literal["automated", "paused", "human", "closed"]
    latest_event_id: int = Field(ge=0)
    messages: list[WebHistoryMessage]


class WebConversationEvent(StrictContract):
    schema_version: Literal["2"] = "2"
    cursor: int = Field(ge=1)
    event_type: str = Field(min_length=3, max_length=100)
    occurred_at: datetime
    payload: dict


class WebEventsResponse(StrictContract):
    after: int = Field(ge=0)
    next_cursor: int = Field(ge=0)
    has_more: bool
    events: list[WebConversationEvent]


class WebSessionResetRequest(StrictContract):
    session_id: UUID
    next_session_id: UUID
    route_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=ROUTE_KEY_PATTERN,
    )
    consent: WebTranscriptConsent

    @model_validator(mode="after")
    def require_rotated_session(self) -> "WebSessionResetRequest":
        if self.session_id == self.next_session_id:
            raise ValueError("next session must differ from current session")
        return self


class WebSessionResetResponse(StrictContract):
    status: Literal["active"] = "active"
    latest_event_id: int = Field(ge=0)
