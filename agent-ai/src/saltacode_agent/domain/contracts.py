"""Versioned provider-independent execution and tool contracts."""

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Reject undeclared fields so internal contracts fail closed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExecutionRequest(StrictModel):
    """One stateless agent turn accepted from the public BFF."""

    request_id: UUID
    session_id: UUID
    input: Annotated[str, Field(min_length=1, max_length=4_000)]
    locale: Annotated[str, Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")] = "es-AR"


class ExecutionResponse(StrictModel):
    request_id: UUID
    session_id: UUID
    status: Literal["completed"] = "completed"
    output: Annotated[str, Field(min_length=1, max_length=16_000)]
    tools_used: tuple[str, ...] = ()


class ErrorResponse(StrictModel):
    request_id: UUID | None = None
    code: str
    message: str
    retryable: bool = False


class ToolStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class ToolInvocation(StrictModel):
    request_id: UUID
    tool_name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(StrictModel):
    """Separate user-safe output from compact model context."""

    request_id: UUID
    tool_name: str
    status: ToolStatus
    output: dict[str, Any] = Field(default_factory=dict)
    model_summary: dict[str, Any] | None = Field(default=None, exclude=True)
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    error_code: str | None = None


class LivenessResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: str


class ReadinessCheck(StrictModel):
    name: str
    ready: bool
    detail: str | None = None


class ReadinessResponse(StrictModel):
    status: Literal["ready", "not_ready"]
    checks: tuple[ReadinessCheck, ...]
