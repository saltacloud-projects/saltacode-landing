"""Consumer-owned port for authenticated inbound channel adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.schemas.inbound import InboundMessageEnvelope, InboundRouteContext


class InboundChannelAdapter(Protocol):
    """Normalize provider payloads without performing persistence or provider I/O."""

    channel: str

    def normalize_messages(
        self,
        payload: Mapping[str, Any],
        *,
        route: InboundRouteContext,
    ) -> tuple[InboundMessageEnvelope, ...]: ...
