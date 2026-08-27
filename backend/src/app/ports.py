from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from app.contracts import AgentRequest, ChatStreamEvent


class AgentGateway(Protocol):
    def stream(
        self,
        request: AgentRequest,
        *,
        correlation_id: str,
    ) -> AsyncIterator[ChatStreamEvent]: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimitBackendError(Exception):
    """The limiter could not make an authoritative decision."""


class RateLimiter(Protocol):
    async def check(self, key: str) -> RateLimitDecision: ...

    async def ready(self) -> bool: ...

    async def aclose(self) -> None: ...
