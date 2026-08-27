"""Versioned private execution contract consumed by trusted channel adapters."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TranscriptConsent(BaseModel):
    granted: bool
    version: str = Field(min_length=1, max_length=80)


class InternalExecutionRequest(BaseModel):
    request_id: UUID
    session_id: UUID
    input: str = Field(min_length=1, max_length=4_000)
    locale: Literal["es-AR", "es", "en"] = "es-AR"
    consent: TranscriptConsent
    route_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9._:-]{0,119}$",
    )


class InternalExecutionResponse(BaseModel):
    request_id: UUID
    session_id: UUID
    status: Literal["completed"] = "completed"
    output: str = Field(min_length=1, max_length=16_000)
    tools_used: tuple[str, ...] = ()
