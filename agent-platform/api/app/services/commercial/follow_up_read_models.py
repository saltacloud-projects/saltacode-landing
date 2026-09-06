"""Agent-scoped, privacy-minimized read models for follow-up operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity
from app.models.outbound import OutboundMessage
from app.schemas.follow_up_operations import (
    FollowUpDetailOut,
    FollowUpEventOut,
    FollowUpQueueItemOut,
)


class FollowUpReadNotFoundError(Exception):
    """The task is absent or outside the selected agent's current ownership."""


@dataclass(frozen=True, slots=True)
class FollowUpQueuePage:
    items: list[FollowUpQueueItemOut]
    total: int


@dataclass(frozen=True, slots=True)
class FollowUpEventPage:
    items: list[FollowUpEventOut]
    total: int


class FollowUpReadService:
    """Project queue state without contact data or command identifiers."""

    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        status: str | None,
        kind: str | None,
        limit: int,
        offset: int,
    ) -> FollowUpQueuePage:
        statement = self._owned_statement(agent_id)
        if status is not None:
            statement = statement.where(FollowUpTask.status == status)
        if kind is not None:
            statement = statement.where(FollowUpTask.kind == kind)
        total = int(
            (
                await db.execute(select(func.count()).select_from(statement.subquery()))
            ).scalar_one()
        )
        rows = (
            await db.execute(
                statement.order_by(
                    FollowUpTask.due_at,
                    FollowUpTask.created_at,
                    FollowUpTask.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return FollowUpQueuePage(
            items=[
                self._queue_item(task, outbound_status)
                for task, outbound_status in rows
            ],
            total=total,
        )

    async def get_task(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> FollowUpDetailOut:
        row = (
            await db.execute(
                self._owned_statement(agent_id).where(FollowUpTask.id == task_id)
            )
        ).one_or_none()
        if row is None:
            raise FollowUpReadNotFoundError("follow-up task not found")
        task, outbound_status = row
        return FollowUpDetailOut(
            **self._queue_item(task, outbound_status).model_dump(),
            conversation_id=task.conversation_id,
            has_retained_source_conversation=task.source_conversation_id is not None,
            quote_version_id=task.quote_version_id,
            scheduled_control_version=task.scheduled_control_version,
            scheduled_automation_version=task.scheduled_automation_version,
            scheduled_policy_version=task.scheduled_policy_version,
            executed_policy_version=task.executed_policy_version,
            has_consent_evidence=task.consent_record_id is not None,
            has_executed_consent_evidence=(task.executed_consent_record_id is not None),
            has_chat_message_evidence=(
                task.had_chat_message_evidence or task.chat_message_id is not None
            ),
            has_outbound_message_evidence=(
                task.had_outbound_message_evidence
                or task.outbound_message_id is not None
            ),
            completed_at=task.completed_at,
            cancelled_at=task.cancelled_at,
        )

    async def list_events(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        task_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> FollowUpEventPage:
        owned = (
            await db.execute(
                select(FollowUpTask.id)
                .join(Opportunity, Opportunity.id == FollowUpTask.opportunity_id)
                .where(
                    FollowUpTask.id == task_id,
                    Opportunity.assigned_agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if owned is None:
            raise FollowUpReadNotFoundError("follow-up task not found")
        total = int(
            (
                await db.execute(
                    select(func.count(FollowUpTaskEvent.id)).where(
                        FollowUpTaskEvent.task_id == task_id
                    )
                )
            ).scalar_one()
        )
        events = list(
            (
                await db.execute(
                    select(FollowUpTaskEvent)
                    .where(FollowUpTaskEvent.task_id == task_id)
                    .order_by(
                        FollowUpTaskEvent.state_version,
                        FollowUpTaskEvent.created_at,
                        FollowUpTaskEvent.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return FollowUpEventPage(
            items=[self._event_out(event) for event in events],
            total=total,
        )

    @staticmethod
    def _owned_statement(agent_id: uuid.UUID):
        return (
            select(FollowUpTask, OutboundMessage.status)
            .join(Opportunity, Opportunity.id == FollowUpTask.opportunity_id)
            .outerjoin(
                OutboundMessage,
                OutboundMessage.id == FollowUpTask.outbound_message_id,
            )
            .where(Opportunity.assigned_agent_id == agent_id)
        )

    @staticmethod
    def _queue_item(
        task: FollowUpTask,
        outbound_status: str | None,
    ) -> FollowUpQueueItemOut:
        return FollowUpQueueItemOut(
            id=task.id,
            opportunity_id=task.opportunity_id,
            assigned_agent_id=task.assigned_agent_id,
            assigned_operator_id=task.assigned_operator_id,
            kind=task.kind,
            status=task.status,
            state_version=task.state_version,
            due_at=task.due_at,
            available_at=task.available_at,
            attempts=task.attempts,
            max_attempts=task.max_attempts,
            is_leased=task.lease_owner is not None,
            outbound_status=outbound_status,
            safe_code=task.last_safe_code,
            review_required_at=task.review_required_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    @staticmethod
    def _event_out(event: FollowUpTaskEvent) -> FollowUpEventOut:
        return FollowUpEventOut(
            id=event.id,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            state_version=event.state_version,
            actor_type=event.actor_type,
            has_actor_agent=event.actor_agent_id is not None,
            has_actor_admin=event.actor_admin_id is not None,
            has_actor_worker=event.actor_worker_id is not None,
            routing_agent_id=event.routing_agent_id,
            automation_agent_id=event.automation_agent_id,
            target_channel=event.target_channel,
            control_version=event.control_version,
            automation_version=event.automation_version,
            scheduled_policy_version=event.scheduled_policy_version,
            executed_policy_version=event.executed_policy_version,
            has_consent_evidence=event.consent_record_id is not None,
            has_executed_consent_evidence=(
                event.executed_consent_record_id is not None
            ),
            has_causal_consent_evidence=(event.caused_by_consent_record_id is not None),
            has_chat_message_evidence=(
                event.had_chat_message_evidence or event.chat_message_id is not None
            ),
            has_outbound_message_evidence=(
                event.had_outbound_message_evidence
                or event.outbound_message_id is not None
            ),
            safe_code=event.safe_code,
            created_at=event.created_at,
        )


follow_up_read_service = FollowUpReadService()
