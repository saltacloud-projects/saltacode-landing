"""Guided commercial progression configuration, not arbitrary workflow code."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

QuoteRequestAction = Literal["keep_agent", "handoff"]


class CommercialProgressionOut(BaseModel):
    agent_id: UUID
    quote_request_action: QuoteRequestAction
    version: int
    is_configured: bool


class CommercialProgressionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_request_action: QuoteRequestAction
    expected_version: int = Field(ge=0)
