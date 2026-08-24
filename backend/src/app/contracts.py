from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


ChatMessage = Annotated[str, StringConstraints(min_length=1, max_length=4_000)]


class ChatRequest(ContractModel):
    session_id: UUID
    client_message_id: UUID
    message: ChatMessage
    locale: Literal["es-AR", "es", "en"] = "es-AR"


class ChatStartedEvent(ContractModel):
    type: Literal["chat.started"] = "chat.started"
    correlation_id: str
    response_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatDeltaEvent(ContractModel):
    type: Literal["chat.delta"] = "chat.delta"
    correlation_id: str
    response_id: UUID
    sequence: int = Field(ge=0)
    delta: str = Field(min_length=1, max_length=4_000)


class ChatErrorEvent(ContractModel):
    type: Literal["chat.error"] = "chat.error"
    correlation_id: str
    response_id: UUID
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    message: str = Field(min_length=1, max_length=240)
    retryable: bool


class ChatDoneEvent(ContractModel):
    type: Literal["chat.done"] = "chat.done"
    correlation_id: str
    response_id: UUID
    outcome: Literal["completed", "failed", "cancelled"]


ChatStreamEvent = Annotated[
    ChatStartedEvent | ChatDeltaEvent | ChatErrorEvent | ChatDoneEvent,
    Field(discriminator="type"),
]


class ProblemDetails(ContractModel):
    type: str = "about:blank"
    title: str
    status: int = Field(ge=400, le=599)
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    detail: str
    correlation_id: str


class HealthStatus(ContractModel):
    status: Literal["ok", "ready", "not_ready"]
