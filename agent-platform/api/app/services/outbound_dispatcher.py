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
from app.services.outbound_follow_up import (
    FollowUpDispatchAuthorizationService,
    FollowUpDispatchBlocked,
    follow_up_dispatch_authorization_service,
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
        follow_up_authorization: FollowUpDispatchAuthorizationService = (
            follow_up_dispatch_authorization_service
        ),
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._worker_id = worker_id
        self._stale_seconds = stale_seconds
        self._adapters = self._build_adapter_registry(adapters)
        self._delivery_service = delivery_service
        self._follow_up_authorization = follow_up_authorization
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
        # Hold the conversation lock through the provider call. A takeover that
        # wins first cancels this claim; one arriving later waits until the call
        # and result commit finish, preserving total order around side effects.
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
                    await self._delivery_service.cancel_claim(
                        db,
                        outbound_message_id=claim.message.id,
                        attempt_id=claim.attempt.id,
                        worker_id=self._worker_id,
                        safe_code="route_snapshot_changed",
                    )
                    return
                route, connection = resolved
                adapter = self._adapters.get(message.adapter_key)
                if adapter is None:
                    await self._delivery_service.cancel_claim(
                        db,
                        outbound_message_id=claim.message.id,
                        attempt_id=claim.attempt.id,
                        worker_id=self._worker_id,
                        safe_code="adapter_unavailable",
                    )
                    return
                try:
                    await self._follow_up_authorization.revalidate(
                        db,
                        message=message,
                    )
                except FollowUpDispatchBlocked as exc:
                    await self._delivery_service.cancel_claim(
                        db,
                        outbound_message_id=claim.message.id,
                        attempt_id=claim.attempt.id,
                        worker_id=self._worker_id,
                        safe_code=exc.safe_code,
                    )
                    return
                try:
                    result = await adapter.deliver(
                        message=message,
                        route=route,
                        connection=connection,
                    )
                except Exception as exc:
                    logger.error(
                        "outbound_adapter_failed",
                        extra={
                            "outbound_message_id": str(message.id),
                            "channel": message.channel,
                            "adapter_key": message.adapter_key,
                            "error_type": type(exc).__name__,
                        },
                    )
                    result = Unknown("adapter_unhandled_error")
                outcome, provider_message_id, safe_code = self._result_fields(result)
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
    def _build_adapter_registry(
        adapters: Iterable[OutboundChannelAdapter],
    ) -> dict[str, OutboundChannelAdapter]:
        registry: dict[str, OutboundChannelAdapter] = {}
        for adapter in adapters:
            adapter_key = adapter.adapter_key.strip()
            if not adapter_key:
                raise ValueError("outbound adapter key cannot be empty")
            if adapter_key in registry:
                raise ValueError(f"duplicate outbound adapter key: {adapter_key}")
            registry[adapter_key] = adapter
        return registry

    @staticmethod
    def _result_fields(
        result: OutboundResult,
    ) -> tuple[DispatchOutcome, str | None, str | None]:
        if isinstance(result, Accepted):
            return DispatchOutcome.ACCEPTED, result.provider_message_id, None
        if isinstance(result, Rejected):
            return DispatchOutcome.FAILED, None, result.safe_code
        if isinstance(result, Unknown):
            return DispatchOutcome.DELIVERY_UNKNOWN, None, result.safe_code
        return DispatchOutcome.DELIVERY_UNKNOWN, None, "adapter_contract_error"

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
                        ChannelAgentRoute.channel == message.channel,
                        ChannelAgentRoute.channel_connection_id
                        == message.channel_connection_id,
                        ChannelAgentRoute.version == message.route_version,
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
                        ChannelConnection.id == message.channel_connection_id,
                        ChannelConnection.channel == message.channel,
                        ChannelConnection.adapter_key == message.adapter_key,
                        ChannelConnection.version == message.connection_version,
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
