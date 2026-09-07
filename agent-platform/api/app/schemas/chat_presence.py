"""Content-free, ephemeral typing contracts; never part of transcript history."""

from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)


class TypingState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    typing: StrictBool = False
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_coherent_expiry(self) -> "TypingState":
        if self.typing != (self.expires_at is not None):
            raise ValueError("Only active typing has an expiry")
        return self


class WebPresence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: TypingState = Field(default_factory=TypingState)


class InboxPresence(WebPresence):
    visitor: TypingState = Field(default_factory=TypingState)


class TypingSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_instance_id: UUID
    sequence: StrictInt = Field(ge=0, le=9_007_199_254_740_991)
    typing: StrictBool


class OperatorTypingSignal(TypingSignal):
    expected_control_version: StrictInt = Field(ge=0, le=9_007_199_254_740_991)
