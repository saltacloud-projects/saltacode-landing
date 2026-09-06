"""Private contract for explicit commercial contact capture from web chat."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.web_chat_v2 import ROUTE_KEY_PATTERN, StrictContract


class WebCommercialContactRequest(StrictContract):
    session_id: UUID
    route_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=ROUTE_KEY_PATTERN,
    )
    client_request_id: UUID
    locale: str = Field(min_length=2, max_length=20)
    policy_version: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=8_000)
    contact_kind: Literal["email", "phone"]
    contact_value: str = Field(min_length=1, max_length=320)
    preferred_delivery_channel: Literal["email", "whatsapp"]
    quote_delivery_consent: Literal[True]
    commercial_follow_up_consent: bool

    @model_validator(mode="after")
    def require_contact_for_delivery_channel(self) -> WebCommercialContactRequest:
        expected_kind = {
            "email": "email",
            "whatsapp": "phone",
        }[self.preferred_delivery_channel]
        if self.contact_kind != expected_kind:
            raise ValueError("contact kind must match the preferred delivery channel")
        return self


class WebCommercialContactAccepted(StrictContract):
    opportunity_id: UUID
    target_agent_id: UUID
    status: Literal["accepted"] = "accepted"
