"""Lifecycle port between channel adapters and the conversation pipeline."""

from __future__ import annotations

import uuid
from typing import Protocol


class ChannelInboundLifecycle(Protocol):
    """Persist ownership snapshots and effect fences before external work."""

    async def inbound_recorded(
        self,
        *,
        conversation_id: uuid.UUID,
        control_version: int,
        automation_agent_id: uuid.UUID,
        automation_version: int,
    ) -> None: ...

    async def before_external_effect(self, *, phase: str) -> None: ...
