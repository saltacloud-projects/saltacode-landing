"""Transactional coordinator for outbound channel adapters."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundMessage
from app.ports.outbound import (
    Accepted,
    OutboundChannelAdapter,
    OutboundResult,
    Rejected,
    Unknown,
)
from app.services.outbound_delivery import (
    ClaimedOutbound,
    DispatchOutcome,
    OutboundDeliveryService,
    outbound_delivery_service,
)

logger = logging.getLogger(__name__)


class OutboundDispatcher:
    """Commit claims, fence ownership, invoke one adapter, then persist outcome."""

    def __init__(
        self,
        *,
        worker_id: str,
        stale_seconds: int,
        adapters: Iterable[OutboundChannelAdapter],
        delivery_service: OutboundDeliveryService = outbound_delivery_service,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._worker_id = worker_id
        self._stale_seconds = stale_seconds
        self._adapters = {adapter.channel: adapter for adapter in adapters}
        self._delivery_service = delivery_service
        self._session_factory = session_factory

    async def run_once(self) -> bool:
        claim = await self.claim_once()
        if claim is None:
            return False
        await self.dispatch_claim(claim)
        return True

    async def claim_once(self) -> ClaimedOutbound | None:
        """Commit the durable claim before returning control to any adapter."""
        async with self._session_factory() as db:
            async with db.begin():
                return await self._delivery_service.claim_next(
                    db,
                    worker_id=self._worker_id,
                    stale_before=datetime.now(timezone.utc)
                    - timedelta(seconds=self._stale_seconds),
                )

    async def dispatch_claim(self, claim: ClaimedOutbound) -> None:
        result = await self._deliver_with_fence(claim)
        if result is None:
            return
        await self._persist_result(claim, result)

    async def _deliver_with_fence(
        self,
        claim: ClaimedOutbound,
    ) -> OutboundResult | None:
        # Hold the conversation lock through the provider call. A takeover that
        # wins first cancels this claim; one arriving later waits until the call
        # finishes, preserving a total order between ownership and side effects.
        async with self._session_factory() as db:
            async with db.begin():
                message = await self._delivery_service.revalidate_claim_for_dispatch(
                    db,
                    outbound_message_id=claim.message.id,
                    attempt_id=claim.attempt.id,
                    worker_id=self._worker_id,
                )
                if message is None:
                    return None
                resolved = await self._load_route_and_connection(db, message)
                if resolved is None:
                    return Rejected("route_unavailable")
                route, connection = resolved
                adapter = self._adapters.get(route.channel)
                if adapter is None:
                    return Rejected("unsupported_channel")
                try:
                    return await adapter.deliver(
                        message=message,
                        route=route,
                        connection=connection,
                    )
                except Exception as exc:
                    logger.error(
                        "outbound_adapter_failed",
                        extra={
                            "outbound_message_id": str(message.id),
                            "channel": route.channel,
                            "error_type": type(exc).__name__,
                        },
                    )
                    return Unknown("adapter_unhandled_error")

    async def _persist_result(
        self,
        claim: ClaimedOutbound,
        result: OutboundResult,
    ) -> None:
        if isinstance(result, Accepted):
            outcome = DispatchOutcome.ACCEPTED
            provider_message_id = result.provider_message_id
            safe_code = None
        elif isinstance(result, Rejected):
            outcome = DispatchOutcome.FAILED
            provider_message_id = None
            safe_code = result.safe_code
        elif isinstance(result, Unknown):
            outcome = DispatchOutcome.DELIVERY_UNKNOWN
            provider_message_id = None
            safe_code = result.safe_code
        else:
            outcome = DispatchOutcome.DELIVERY_UNKNOWN
            provider_message_id = None
            safe_code = "adapter_contract_error"

        async with self._session_factory() as db:
            async with db.begin():
                await self._delivery_service.record_dispatch_outcome(
                    db,
                    outbound_message_id=claim.message.id,
                    attempt_id=claim.attempt.id,
                    worker_id=self._worker_id,
                    outcome=outcome,
                    provider_message_id=provider_message_id,
                    safe_code=safe_code,
                )

    @staticmethod
    async def _load_route_and_connection(
        db: AsyncSession,
        message: OutboundMessage,
    ) -> tuple[ChannelAgentRoute, ChannelConnection] | None:
        route = (
            (
                await db.execute(
                    select(ChannelAgentRoute)
                    .where(
                        ChannelAgentRoute.id == message.channel_route_id,
                        ChannelAgentRoute.agent_id == message.agent_id,
                        ChannelAgentRoute.is_active.is_(True),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        if route is None:
            return None
        connection = (
            (
                await db.execute(
                    select(ChannelConnection)
                    .where(
                        ChannelConnection.id == route.channel_connection_id,
                        ChannelConnection.is_active.is_(True),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        if connection is None:
            return None
        return route, connection
