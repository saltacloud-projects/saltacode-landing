"""Safe agent-scoped read model for outbound delivery incidents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryEvent,
    OutboundMessage,
)
from app.models.platform import ChatConversation
from app.schemas.deliveries import (
    DeliveryAttemptOut,
    DeliveryDetailOut,
    DeliveryEventOut,
    DeliveryStatus,
    DeliverySummaryOut,
)

_FIFO_BLOCKING_STATUSES = ("queued", "dispatching", "delivery_unknown")


class DeliveryReviewNotFoundError(Exception):
    """The delivery is absent or belongs to another agent."""


@dataclass(frozen=True, slots=True)
class DeliveryReviewPage:
    items: list[DeliverySummaryOut]
    total: int


class OutboundDeliveryReviewService:
    """Expose operational evidence without message bodies or provider payloads."""

    async def list_deliveries(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        channel: str | None = None,
        delivery_status: DeliveryStatus | None = None,
        conversation_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DeliveryReviewPage:
        statement = self._summary_statement(agent_id)
        statement = self._apply_filters(
            statement,
            channel=channel,
            delivery_status=delivery_status,
            conversation_id=conversation_id,
        )
        total = int(
            (
                await db.execute(select(func.count()).select_from(statement.subquery()))
            ).scalar_one()
        )
        incident_priority = case(
            (OutboundMessage.status == DeliveryStatus.DELIVERY_UNKNOWN.value, 0),
            (OutboundMessage.status == DeliveryStatus.FAILED.value, 1),
            else_=2,
        )
        rows = (
            await db.execute(
                statement.order_by(
                    incident_priority,
                    OutboundMessage.updated_at.desc(),
                    OutboundMessage.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return DeliveryReviewPage(
            items=[self._summary_out(*row) for row in rows],
            total=total,
        )

    async def get_delivery(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        delivery_id: uuid.UUID,
    ) -> DeliveryDetailOut:
        row = (
            await db.execute(
                self._summary_statement(agent_id).where(
                    OutboundMessage.id == delivery_id
                )
            )
        ).one_or_none()
        if row is None:
            raise DeliveryReviewNotFoundError("delivery not found")

        message = row[0]
        attempts = list(
            (
                await db.execute(
                    select(OutboundAttempt)
                    .where(OutboundAttempt.outbound_message_id == delivery_id)
                    .order_by(
                        OutboundAttempt.attempt_number,
                        OutboundAttempt.created_at,
                    )
                )
            )
            .scalars()
            .all()
        )
        events = list(
            (
                await db.execute(
                    select(OutboundDeliveryEvent)
                    .where(OutboundDeliveryEvent.outbound_message_id == delivery_id)
                    .order_by(
                        OutboundDeliveryEvent.created_at,
                        OutboundDeliveryEvent.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        summary = self._summary_out(*row)
        return DeliveryDetailOut(
            **summary.model_dump(),
            channel_route_id=message.channel_route_id,
            chat_message_id=message.chat_message_id,
            control_version=message.control_version,
            accepted_at=message.accepted_at,
            delivered_at=message.delivered_at,
            attempts=[
                DeliveryAttemptOut(
                    id=attempt.id,
                    attempt_number=attempt.attempt_number,
                    control_version=attempt.control_version,
                    created_at=attempt.created_at,
                )
                for attempt in attempts
            ],
            events=[
                DeliveryEventOut(
                    id=event.id,
                    attempt_id=event.attempt_id,
                    event_type=event.event_type,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    actor_type=event.actor_type,
                    safe_code=event.safe_code,
                    created_at=event.created_at,
                )
                for event in events
            ],
        )

    @staticmethod
    def _summary_statement(agent_id: uuid.UUID) -> Select:
        attempt_counts = (
            select(
                OutboundAttempt.outbound_message_id.label("message_id"),
                func.count(OutboundAttempt.id).label("attempt_count"),
            )
            .group_by(OutboundAttempt.outbound_message_id)
            .subquery()
        )
        latest_event = aliased(OutboundDeliveryEvent)
        latest_safe_code = (
            select(latest_event.safe_code)
            .where(
                latest_event.outbound_message_id == OutboundMessage.id,
                latest_event.safe_code.is_not(None),
            )
            .order_by(latest_event.created_at.desc(), latest_event.id.desc())
            .limit(1)
            .correlate(OutboundMessage)
            .scalar_subquery()
        )
        later_message = aliased(OutboundMessage)
        blocked_message_count = (
            select(func.count(later_message.id))
            .where(
                later_message.conversation_id == OutboundMessage.conversation_id,
                later_message.sequence > OutboundMessage.sequence,
                later_message.status == DeliveryStatus.QUEUED.value,
            )
            .correlate(OutboundMessage)
            .scalar_subquery()
        )
        return (
            select(
                OutboundMessage,
                ChatConversation.channel,
                func.coalesce(attempt_counts.c.attempt_count, 0),
                latest_safe_code,
                blocked_message_count,
            )
            .join(
                ChatConversation,
                ChatConversation.id == OutboundMessage.conversation_id,
            )
            .outerjoin(
                attempt_counts,
                attempt_counts.c.message_id == OutboundMessage.id,
            )
            .where(
                OutboundMessage.agent_id == agent_id,
                ChatConversation.agent_id == agent_id,
            )
        )

    @staticmethod
    def _apply_filters(
        statement: Select,
        *,
        channel: str | None,
        delivery_status: DeliveryStatus | None,
        conversation_id: uuid.UUID | None,
    ) -> Select:
        if channel:
            statement = statement.where(ChatConversation.channel == channel)
        if delivery_status:
            statement = statement.where(OutboundMessage.status == delivery_status.value)
        if conversation_id:
            statement = statement.where(
                OutboundMessage.conversation_id == conversation_id
            )
        return statement

    @classmethod
    def _summary_out(
        cls,
        message: OutboundMessage,
        channel: str,
        attempt_count: int,
        latest_safe_code: str | None,
        blocked_message_count: int,
    ) -> DeliverySummaryOut:
        is_fifo_blocking = message.status in _FIFO_BLOCKING_STATUSES
        return DeliverySummaryOut(
            id=message.id,
            conversation_id=message.conversation_id,
            channel=channel,
            status=message.status,
            kind=message.kind,
            sender_type=message.sender_type,
            sequence=message.sequence,
            correlation_id=message.correlation_id,
            provider_reference=cls._mask_provider_reference(
                message.provider_message_id
            ),
            attempt_count=int(attempt_count or 0),
            latest_safe_code=latest_safe_code,
            is_fifo_blocking=is_fifo_blocking,
            blocked_message_count=(
                int(blocked_message_count or 0) if is_fifo_blocking else 0
            ),
            created_at=message.created_at,
            updated_at=message.updated_at,
        )

    @staticmethod
    def _mask_provider_reference(value: str | None) -> str | None:
        if not value:
            return None
        suffix = value[-6:] if len(value) > 6 else value[-2:]
        return f"…{suffix}"


outbound_delivery_review_service = OutboundDeliveryReviewService()
