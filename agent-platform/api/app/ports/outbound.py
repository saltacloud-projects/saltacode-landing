"""Channel-neutral outbound delivery contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundMessage


@dataclass(frozen=True)
class Accepted:
    """The provider durably accepted the outbound message."""

    provider_message_id: str


@dataclass(frozen=True)
class Rejected:
    """The command was definitively rejected before any ambiguous effect."""

    safe_code: str


@dataclass(frozen=True)
class Unknown:
    """The provider may have accepted the command; automatic retry is unsafe."""

    safe_code: str


OutboundResult: TypeAlias = Accepted | Rejected | Unknown


class OutboundChannelAdapter(Protocol):
    """Deliver one frozen command through one resolved persisted route."""

    adapter_key: str

    async def deliver(
        self,
        *,
        message: OutboundMessage,
        route: ChannelAgentRoute,
        connection: ChannelConnection,
    ) -> OutboundResult: ...
