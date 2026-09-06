"""Administration contracts for deterministic agent handoff routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AgentHandoffTrigger = Literal["quote_requested", "manual_escalation"]


class AgentHandoffRouteCreateRequest(BaseModel):
    target_agent_id: uuid.UUID
    trigger: AgentHandoffTrigger
    is_active: bool = True
    idempotency_key: str = Field(min_length=1, max_length=220)


class AgentHandoffRouteUpdateRequest(BaseModel):
    target_agent_id: uuid.UUID | None = None
    is_active: bool | None = None
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=220)

    @model_validator(mode="after")
    def require_change(self) -> AgentHandoffRouteUpdateRequest:
        if self.target_agent_id is None and self.is_active is None:
            raise ValueError("at least one route field must be provided")
        return self


class AgentHandoffRouteDeactivateRequest(BaseModel):
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=220)


class AgentHandoffRouteOut(BaseModel):
    id: uuid.UUID
    source_agent_id: uuid.UUID
    target_agent_id: uuid.UUID
    trigger: AgentHandoffTrigger
    is_active: bool
    control_version: int
    created_by_admin_id: uuid.UUID
    updated_by_admin_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
