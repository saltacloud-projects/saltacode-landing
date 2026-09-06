"""Fail-closed execution and reconciliation for durable commercial follow-ups."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.contact import Contact, ContactPoint
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity
from app.models.outbound import OutboundMessage
from app.models.platform import ChatConversation
from app.models.quote import QuoteRequest, QuoteVersion
from app.services.channel_catalog import (
    ChannelAdapterUnavailable,
    ChannelCatalogError,
    require_implemented_adapter,
)
from app.services.commercial.consent_scope import (
    ConsentScope,
    acquire_consent_scope_lock,
)
from app.services.commercial.consents import ConsentPurpose, ConsentService
from app.services.commercial.contact_crypto import (
    ContactCrypto,
    ContactCryptoError,
    contact_crypto,
)
from app.services.outbound_delivery import (
    OutboundDeliveryError,
    OutboundDeliveryService,
    OutboundKind,
    OutboundSenderType,
    outbound_delivery_service,
)

_ACTIVE_TASK_STATUSES = (
    "scheduled",
    "dispatch_queued",
    "in_progress",
    "review_required",
)
_DEFINITIVE_OUTBOUND_STATUSES = ("accepted", "delivered", "read")
_FAILED_OUTBOUND_SAFE_CODES = {
    "cancelled": "follow_up_outbound_cancelled",
    "delivery_unknown": "follow_up_delivery_unknown",
    "failed": "follow_up_outbound_failed",
}
_CLOSED_OPPORTUNITY_STAGES = ("won", "lost")
_PHONE_DIGITS = re.compile(r"\D")


@dataclass(frozen=True, slots=True)
class ClaimedFollowUp:
    task_id: uuid.UUID
    state_version: int
    worker_id: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class FollowUpExecutionResult:
    processed: bool
    safe_code: str | None = None


class FollowUpExecutionService:
    """Own task claims, policy fences, durable enqueue, and outcome projection."""

    def __init__(
        self,
        *,
        consents: ConsentService | None = None,
        outbound: OutboundDeliveryService = outbound_delivery_service,
        crypto: ContactCrypto = contact_crypto,
    ) -> None:
        self._consents = consents or ConsentService()
        self._outbound = outbound
        self._crypto = crypto

    async def recover_expired_leases(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> int:
        """Quarantine expired claims because execution progress is uncertain."""

        normalized_worker = _worker_id(worker_id)
        event_time = _aware_utc(now or datetime.now(UTC))
        tasks = list(
            (
                await db.execute(
                    select(FollowUpTask)
                    .where(
                        FollowUpTask.status == "in_progress",
                        FollowUpTask.lease_expires_at.is_not(None),
                        FollowUpTask.lease_expires_at <= event_time,
                    )
                    .order_by(FollowUpTask.lease_expires_at, FollowUpTask.id)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for task in tasks:
            await self._move_to_review(
                db,
                task=task,
                worker_id=normalized_worker,
                safe_code="follow_up_lease_expired",
                event_time=event_time,
            )
        if tasks:
            await db.flush()
        return len(tasks)

    async def claim_next(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> ClaimedFollowUp | None:
        """Claim one FIFO head after applying policy timing and execution limits."""

        normalized_worker = _worker_id(worker_id)
        if lease_duration <= timedelta(0):
            raise ValueError("follow-up lease duration must be positive")
        event_time = _aware_utc(now or datetime.now(UTC))

        while True:
            task = (
                (
                    await db.execute(
                        self._eligible_head_statement(event_time).with_for_update(
                            skip_locked=True
                        )
                    )
                )
                .scalars()
                .first()
            )
            if task is None:
                return None
            conversation = await self._load_source_conversation(db, task, lock=True)
            if conversation is None:
                await self._move_to_review(
                    db,
                    task=task,
                    worker_id=normalized_worker,
                    safe_code="legacy_follow_up_context_unknown",
                    event_time=event_time,
                    routing_agent_id=None,
                )
                continue
            policy = await self._load_policy(
                db,
                agent_id=task.assigned_agent_id,
                lock=True,
            )
            policy_failure = self._policy_failure(task=task, policy=policy)
            if policy_failure is not None:
                await self._move_to_review(
                    db,
                    task=task,
                    worker_id=normalized_worker,
                    safe_code=policy_failure,
                    event_time=event_time,
                    routing_agent_id=conversation.agent_id,
                )
                continue
            assert policy is not None

            deferred_until, defer_code = await self._deferred_until(
                db,
                task=task,
                policy=policy,
                now=event_time,
            )
            if deferred_until is not None and defer_code is not None:
                self._defer(
                    db,
                    task=task,
                    worker_id=normalized_worker,
                    available_at=deferred_until,
                    safe_code=defer_code,
                    event_time=event_time,
                    routing_agent_id=conversation.agent_id,
                )
                continue
            if task.attempts >= min(task.max_attempts, policy.max_attempts):
                await self._move_to_review(
                    db,
                    task=task,
                    worker_id=normalized_worker,
                    safe_code="follow_up_attempt_limit_reached",
                    event_time=event_time,
                    routing_agent_id=conversation.agent_id,
                )
                continue

            previous_status = task.status
            task.status = "in_progress"
            task.state_version += 1
            task.attempts += 1
            task.executed_policy_version = policy.version
            task.lease_owner = normalized_worker
            task.lease_expires_at = event_time + lease_duration
            task.last_safe_code = None
            db.add(
                _task_event(
                    task=task,
                    event_type="transitioned",
                    from_status=previous_status,
                    to_status="in_progress",
                    worker_id=normalized_worker,
                    routing_agent_id=conversation.agent_id,
                    safe_code=None,
                    event_time=event_time,
                    include_outbound=False,
                )
            )
            await db.flush()
            return ClaimedFollowUp(
                task_id=task.id,
                state_version=task.state_version,
                worker_id=normalized_worker,
                lease_expires_at=task.lease_expires_at,
            )

    async def enqueue_claim(
        self,
        db: AsyncSession,
        *,
        claim: ClaimedFollowUp,
        now: datetime | None = None,
    ) -> FollowUpExecutionResult:
        """Revalidate one committed claim and atomically enqueue its delivery."""

        event_time = _aware_utc(now or datetime.now(UTC))
        task = await self._lock_owned_claim(db, claim=claim)
        if task is None:
            return FollowUpExecutionResult(processed=False)
        if task.lease_expires_at is None or task.lease_expires_at <= event_time:
            await self._move_to_review(
                db,
                task=task,
                worker_id=claim.worker_id,
                safe_code="follow_up_lease_expired",
                event_time=event_time,
            )
            return FollowUpExecutionResult(
                processed=True,
                safe_code="follow_up_lease_expired",
            )

        try:
            graph = await self._load_execution_graph(db, task=task)
            await self._assert_execution_allowed(
                db,
                graph=graph,
                now=event_time,
            )
            delivery_conversation = await self._resolve_delivery_conversation(
                db,
                graph=graph,
            )
            body = _compose_message(task.kind)
            queued = await self._outbound.enqueue(
                db,
                conversation_id=delivery_conversation.id,
                agent_id=delivery_conversation.agent_id,
                chat_message_id=None,
                kind=OutboundKind.TEXT,
                payload={"text": body},
                sender_type=OutboundSenderType.AUTOMATION,
                control_version=delivery_conversation.control_version,
                automation_agent_id=task.assigned_agent_id,
                automation_version=delivery_conversation.automation_version,
                idempotency_key=f"follow-up:{task.id}:delivery",
                correlation_id=task.correlation_id,
            )
        except _ExecutionBlocked as exc:
            await self._move_to_review(
                db,
                task=task,
                worker_id=claim.worker_id,
                safe_code=exc.safe_code,
                event_time=event_time,
            )
            return FollowUpExecutionResult(processed=True, safe_code=exc.safe_code)
        except OutboundDeliveryError:
            await self._move_to_review(
                db,
                task=task,
                worker_id=claim.worker_id,
                safe_code="follow_up_route_unavailable",
                event_time=event_time,
            )
            return FollowUpExecutionResult(
                processed=True,
                safe_code="follow_up_route_unavailable",
            )

        if queued.duplicate and task.outbound_message_id not in (
            None,
            queued.message.id,
        ):
            await self._move_to_review(
                db,
                task=task,
                worker_id=claim.worker_id,
                safe_code="follow_up_outbound_conflict",
                event_time=event_time,
            )
            return FollowUpExecutionResult(
                processed=True,
                safe_code="follow_up_outbound_conflict",
            )
        previous_status = task.status
        task.outbound_message_id = queued.message.id
        task.status = "dispatch_queued"
        task.state_version += 1
        task.lease_owner = None
        task.lease_expires_at = None
        task.last_safe_code = None
        db.add(
            _task_event(
                task=task,
                event_type="transitioned",
                from_status=previous_status,
                to_status="dispatch_queued",
                worker_id=claim.worker_id,
                routing_agent_id=graph.source_conversation.agent_id,
                safe_code=None,
                event_time=event_time,
                include_outbound=True,
            )
        )
        await db.flush()
        return FollowUpExecutionResult(processed=True)

    async def mark_claim_error_for_review(
        self,
        db: AsyncSession,
        *,
        claim: ClaimedFollowUp,
        now: datetime | None = None,
    ) -> bool:
        """Fence an unexpected local failure without retrying the claimed action."""

        task = await self._lock_owned_claim(db, claim=claim)
        if task is None:
            return False
        await self._move_to_review(
            db,
            task=task,
            worker_id=claim.worker_id,
            safe_code="follow_up_worker_error",
            event_time=_aware_utc(now or datetime.now(UTC)),
        )
        return True

    async def reconcile_next(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> FollowUpExecutionResult:
        """Project one definitive outbound result back into its follow-up task."""

        normalized_worker = _worker_id(worker_id)
        event_time = _aware_utc(now or datetime.now(UTC))
        task = (
            (
                await db.execute(
                    select(FollowUpTask)
                    .outerjoin(
                        OutboundMessage,
                        OutboundMessage.id == FollowUpTask.outbound_message_id,
                    )
                    .where(
                        FollowUpTask.status == "dispatch_queued",
                        or_(
                            FollowUpTask.outbound_message_id.is_(None),
                            OutboundMessage.status.in_(
                                (
                                    *_DEFINITIVE_OUTBOUND_STATUSES,
                                    *_FAILED_OUTBOUND_SAFE_CODES,
                                )
                            ),
                        ),
                    )
                    .order_by(FollowUpTask.updated_at, FollowUpTask.id)
                    .limit(1)
                    .with_for_update(of=FollowUpTask, skip_locked=True)
                )
            )
            .scalars()
            .first()
        )
        if task is None:
            return FollowUpExecutionResult(processed=False)
        message = (
            await db.get(OutboundMessage, task.outbound_message_id)
            if task.outbound_message_id is not None
            else None
        )
        if (
            message is not None
            and message.status in _DEFINITIVE_OUTBOUND_STATUSES
            and task.executed_consent_record_id is not None
        ):
            source = await self._load_source_conversation(db, task, lock=True)
            if source is None:
                await self._move_to_review(
                    db,
                    task=task,
                    worker_id=normalized_worker,
                    safe_code="legacy_follow_up_context_unknown",
                    event_time=event_time,
                    routing_agent_id=None,
                )
                return FollowUpExecutionResult(
                    processed=True,
                    safe_code="legacy_follow_up_context_unknown",
                )
            previous_status = task.status
            task.status = "completed"
            task.state_version += 1
            task.completed_at = event_time
            task.last_safe_code = None
            db.add(
                _task_event(
                    task=task,
                    event_type="transitioned",
                    from_status=previous_status,
                    to_status="completed",
                    worker_id=normalized_worker,
                    routing_agent_id=source.agent_id,
                    safe_code=None,
                    event_time=event_time,
                    include_outbound=False,
                )
            )
            await db.flush()
            return FollowUpExecutionResult(processed=True)

        if message is None:
            safe_code = "follow_up_outbound_missing"
        elif message.status in _DEFINITIVE_OUTBOUND_STATUSES:
            safe_code = "follow_up_consent_evidence_missing"
        else:
            safe_code = _FAILED_OUTBOUND_SAFE_CODES.get(
                message.status,
                "follow_up_outbound_state_unknown",
            )
        await self._move_to_review(
            db,
            task=task,
            worker_id=normalized_worker,
            safe_code=safe_code,
            event_time=event_time,
        )
        return FollowUpExecutionResult(processed=True, safe_code=safe_code)

    @staticmethod
    def _eligible_head_statement(now: datetime):
        earlier = aliased(FollowUpTask)
        is_earlier = or_(
            earlier.due_at < FollowUpTask.due_at,
            and_(
                earlier.due_at == FollowUpTask.due_at,
                earlier.created_at < FollowUpTask.created_at,
            ),
            and_(
                earlier.due_at == FollowUpTask.due_at,
                earlier.created_at == FollowUpTask.created_at,
                earlier.id < FollowUpTask.id,
            ),
        )
        blocking_head = exists(
            select(earlier.id).where(
                earlier.fifo_key == FollowUpTask.fifo_key,
                earlier.status.in_(_ACTIVE_TASK_STATUSES),
                is_earlier,
            )
        )
        return (
            select(FollowUpTask)
            .where(
                FollowUpTask.status == "scheduled",
                FollowUpTask.due_at <= now,
                FollowUpTask.available_at <= now,
                ~blocking_head,
            )
            .order_by(FollowUpTask.due_at, FollowUpTask.created_at, FollowUpTask.id)
            .limit(1)
        )

    async def _deferred_until(
        self,
        db: AsyncSession,
        *,
        task: FollowUpTask,
        policy: CommercialAutomationPolicy,
        now: datetime,
    ) -> tuple[datetime | None, str | None]:
        quiet_end = _quiet_hours_end(policy=policy, now=now)
        if quiet_end is not None:
            return quiet_end, "follow_up_quiet_hours"

        last_claim_at = (
            await db.execute(
                select(func.max(FollowUpTaskEvent.created_at))
                .join(FollowUpTask, FollowUpTask.id == FollowUpTaskEvent.task_id)
                .where(
                    FollowUpTask.fifo_key == task.fifo_key,
                    FollowUpTaskEvent.to_status == "in_progress",
                )
            )
        ).scalar_one()
        if last_claim_at is not None:
            interval_end = last_claim_at + timedelta(
                seconds=policy.min_interval_seconds
            )
            if interval_end > now:
                return interval_end, "follow_up_min_interval"

        day_start, next_day = _local_day_bounds(policy=policy, now=now)
        claimed_today = (
            await db.execute(
                select(func.count(FollowUpTaskEvent.id)).where(
                    FollowUpTaskEvent.automation_agent_id == task.assigned_agent_id,
                    FollowUpTaskEvent.to_status == "in_progress",
                    FollowUpTaskEvent.created_at >= day_start,
                    FollowUpTaskEvent.created_at < next_day,
                )
            )
        ).scalar_one()
        if claimed_today >= policy.max_daily_tasks:
            return next_day, "follow_up_daily_limit"
        return None, None

    @staticmethod
    def _defer(
        db: AsyncSession,
        *,
        task: FollowUpTask,
        worker_id: str,
        available_at: datetime,
        safe_code: str,
        event_time: datetime,
        routing_agent_id: uuid.UUID,
    ) -> None:
        task.available_at = available_at
        task.executed_policy_version = task.scheduled_policy_version
        task.last_safe_code = safe_code
        task.state_version += 1
        db.add(
            _task_event(
                task=task,
                event_type="deferred",
                from_status="scheduled",
                to_status="scheduled",
                worker_id=worker_id,
                routing_agent_id=routing_agent_id,
                safe_code=safe_code,
                event_time=event_time,
                include_outbound=False,
            )
        )

    async def _move_to_review(
        self,
        db: AsyncSession,
        *,
        task: FollowUpTask,
        worker_id: str,
        safe_code: str,
        event_time: datetime,
        routing_agent_id: uuid.UUID | None = None,
    ) -> None:
        previous_status = task.status
        if routing_agent_id is None and task.conversation_id is not None:
            source = await self._load_source_conversation(db, task, lock=True)
            routing_agent_id = source.agent_id if source else None
        task.status = "review_required"
        task.state_version += 1
        task.lease_owner = None
        task.lease_expires_at = None
        task.review_required_at = event_time
        task.last_safe_code = safe_code
        db.add(
            _task_event(
                task=task,
                event_type="transitioned",
                from_status=previous_status,
                to_status="review_required",
                worker_id=worker_id,
                routing_agent_id=routing_agent_id,
                safe_code=safe_code,
                event_time=event_time,
                include_outbound=False,
            )
        )
        await db.flush()

    @staticmethod
    async def _load_source_conversation(
        db: AsyncSession,
        task: FollowUpTask,
        *,
        lock: bool,
    ) -> ChatConversation | None:
        if task.conversation_id is None:
            return None
        statement = select(ChatConversation).where(
            ChatConversation.id == task.conversation_id
        )
        if lock:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    @staticmethod
    async def _load_policy(
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        lock: bool,
    ) -> CommercialAutomationPolicy | None:
        statement = select(CommercialAutomationPolicy).where(
            CommercialAutomationPolicy.agent_id == agent_id
        )
        if lock:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _policy_failure(
        *,
        task: FollowUpTask,
        policy: CommercialAutomationPolicy | None,
    ) -> str | None:
        if policy is None:
            return "follow_up_policy_missing"
        if policy.version != task.scheduled_policy_version:
            return "follow_up_policy_changed"
        if not policy.is_enabled:
            return "follow_up_policy_disabled"
        if task.kind not in policy.allowed_kinds:
            return "follow_up_kind_disabled"
        return None

    @staticmethod
    async def _lock_owned_claim(
        db: AsyncSession,
        *,
        claim: ClaimedFollowUp,
    ) -> FollowUpTask | None:
        return (
            await db.execute(
                select(FollowUpTask)
                .where(
                    FollowUpTask.id == claim.task_id,
                    FollowUpTask.status == "in_progress",
                    FollowUpTask.state_version == claim.state_version,
                    FollowUpTask.lease_owner == claim.worker_id,
                    FollowUpTask.lease_expires_at == claim.lease_expires_at,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def _load_execution_graph(
        self,
        db: AsyncSession,
        *,
        task: FollowUpTask,
    ) -> _ExecutionGraph:
        opportunity = await db.get(Opportunity, task.opportunity_id)
        source = await self._load_source_conversation(db, task, lock=True)
        contact = (
            await db.get(Contact, opportunity.contact_id)
            if opportunity is not None
            else None
        )
        point = (
            await db.get(ContactPoint, task.contact_point_id)
            if task.contact_point_id is not None
            else None
        )
        policy = await self._load_policy(
            db,
            agent_id=task.assigned_agent_id,
            lock=True,
        )
        if None in (opportunity, source, contact, point, policy):
            raise _ExecutionBlocked("follow_up_execution_context_changed")
        return _ExecutionGraph(
            task=task,
            opportunity=opportunity,
            source_conversation=source,
            contact=contact,
            point=point,
            policy=policy,
        )

    async def _assert_execution_allowed(
        self,
        db: AsyncSession,
        *,
        graph: _ExecutionGraph,
        now: datetime,
    ) -> None:
        task = graph.task
        source = graph.source_conversation
        opportunity = graph.opportunity
        policy_failure = self._policy_failure(task=task, policy=graph.policy)
        if policy_failure is not None:
            raise _ExecutionBlocked(policy_failure)
        if (
            opportunity.assigned_agent_id != task.assigned_agent_id
            or opportunity.assigned_operator_id != task.assigned_operator_id
            or opportunity.stage in _CLOSED_OPPORTUNITY_STAGES
        ):
            raise _ExecutionBlocked("follow_up_opportunity_changed")
        if (
            source.status != "active"
            or source.control_mode != "automated"
            or source.control_version != task.scheduled_control_version
        ):
            raise _ExecutionBlocked("follow_up_control_changed")
        if (
            source.automation_agent_id != task.assigned_agent_id
            or source.automation_version != task.scheduled_automation_version
        ):
            raise _ExecutionBlocked("follow_up_automation_changed")
        if (
            graph.contact.status == "archived"
            or graph.contact.principal_id != source.principal_id
            or graph.point.contact_id != graph.contact.id
            or graph.point.verification_status != "verified"
        ):
            raise _ExecutionBlocked("follow_up_contact_changed")
        expected_kind = {"email": "email", "whatsapp": "phone"}.get(task.target_channel)
        if expected_kind is None:
            raise _ExecutionBlocked("follow_up_channel_unsupported")
        if graph.point.kind != expected_kind:
            raise _ExecutionBlocked("follow_up_contact_changed")
        if task.kind == "proposal_reminder":
            issued = (
                await db.execute(
                    select(QuoteVersion.id)
                    .join(
                        QuoteRequest,
                        QuoteRequest.id == QuoteVersion.quote_request_id,
                    )
                    .where(
                        QuoteVersion.id == task.quote_version_id,
                        QuoteVersion.status == "issued",
                        QuoteRequest.opportunity_id == opportunity.id,
                    )
                )
            ).scalar_one_or_none()
            if issued is None:
                raise _ExecutionBlocked("follow_up_quote_evidence_changed")

        scope = ConsentScope(
            routing_agent_id=source.agent_id,
            principal_id=graph.contact.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            source_conversation_id=source.id,
            target_channel=task.target_channel,
            contact_point_id=graph.point.id,
        )
        await acquire_consent_scope_lock(db, scope=scope)
        effective = await self._consents.effective(
            db,
            agent_id=source.agent_id,
            principal_id=graph.contact.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            contact_point_id=graph.point.id,
            source_conversation_id=source.id,
            target_channel=task.target_channel,
            at=now,
        )
        if not effective.granted or effective.record is None:
            raise _ExecutionBlocked("follow_up_consent_missing")

    async def _resolve_delivery_conversation(
        self,
        db: AsyncSession,
        *,
        graph: _ExecutionGraph,
    ) -> ChatConversation:
        channel = graph.task.target_channel
        if channel != "whatsapp":
            raise _ExecutionBlocked("follow_up_channel_not_implemented")
        try:
            target = self._crypto.decrypt(graph.point.ciphertext)
        except ContactCryptoError as exc:
            raise _ExecutionBlocked("follow_up_contact_unavailable") from exc
        target_digits = _phone_digits(target)
        if not target_digits:
            raise _ExecutionBlocked("follow_up_contact_unavailable")

        candidates = list(
            (
                await db.execute(
                    select(ChatConversation)
                    .where(
                        ChatConversation.agent_id == graph.source_conversation.agent_id,
                        ChatConversation.principal_id == graph.contact.principal_id,
                        ChatConversation.channel == channel,
                        ChatConversation.status == "active",
                        ChatConversation.control_mode == "automated",
                        ChatConversation.automation_agent_id
                        == graph.task.assigned_agent_id,
                        ChatConversation.channel_route_id.is_not(None),
                    )
                    .order_by(ChatConversation.updated_at.desc(), ChatConversation.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        matches = [
            conversation
            for conversation in candidates
            if _phone_digits(conversation.external_thread_id) == target_digits
        ]
        if len(matches) != 1:
            raise _ExecutionBlocked("follow_up_target_conversation_unavailable")
        conversation = matches[0]
        route = await db.get(ChannelAgentRoute, conversation.channel_route_id)
        connection = (
            await db.get(ChannelConnection, route.channel_connection_id)
            if route is not None
            else None
        )
        if (
            route is None
            or connection is None
            or not route.is_active
            or not connection.is_active
            or route.agent_id != conversation.agent_id
            or route.channel != channel
            or connection.channel != channel
        ):
            raise _ExecutionBlocked("follow_up_route_unavailable")
        try:
            require_implemented_adapter(
                channel=channel,
                adapter_key=connection.adapter_key,
            )
        except (ChannelAdapterUnavailable, ChannelCatalogError) as exc:
            raise _ExecutionBlocked("follow_up_channel_not_implemented") from exc
        return conversation


@dataclass(frozen=True, slots=True)
class _ExecutionGraph:
    task: FollowUpTask
    opportunity: Opportunity
    source_conversation: ChatConversation
    contact: Contact
    point: ContactPoint
    policy: CommercialAutomationPolicy


class _ExecutionBlocked(Exception):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


def _compose_message(kind: str) -> str:
    messages = {
        "commercial_follow_up": (
            "Hola, retomamos tu consulta para saber si necesitás ayuda con el "
            "próximo paso."
        ),
        "meeting_coordination": (
            "Hola, podemos coordinar una reunión para continuar. "
            "¿Qué disponibilidad te resulta conveniente?"
        ),
        "proposal_reminder": (
            "Hola, queremos confirmar si pudiste revisar la propuesta enviada. "
            "Si querés, coordinamos el próximo paso."
        ),
    }
    try:
        return messages[kind]
    except KeyError as exc:
        raise _ExecutionBlocked("follow_up_kind_unsupported") from exc


def _quiet_hours_end(
    *,
    policy: CommercialAutomationPolicy,
    now: datetime,
) -> datetime | None:
    start = policy.quiet_hours_start
    end = policy.quiet_hours_end
    if start is None or end is None:
        return None
    timezone = ZoneInfo(policy.timezone)
    local_now = now.astimezone(timezone)
    local_time = local_now.timetz().replace(tzinfo=None)
    if start < end:
        if not start <= local_time < end:
            return None
        end_date = local_now.date()
    else:
        if local_time >= start:
            end_date = local_now.date() + timedelta(days=1)
        elif local_time < end:
            end_date = local_now.date()
        else:
            return None
    local_end = datetime.combine(end_date, end, tzinfo=timezone)
    return local_end.astimezone(UTC)


def _local_day_bounds(
    *,
    policy: CommercialAutomationPolicy,
    now: datetime,
) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(policy.timezone)
    local_date: date = now.astimezone(timezone).date()
    local_start = datetime.combine(local_date, time.min, tzinfo=timezone)
    local_next = datetime.combine(
        local_date + timedelta(days=1),
        time.min,
        tzinfo=timezone,
    )
    return local_start.astimezone(UTC), local_next.astimezone(UTC)


def _task_event(
    *,
    task: FollowUpTask,
    event_type: str,
    from_status: str,
    to_status: str,
    worker_id: str,
    routing_agent_id: uuid.UUID | None,
    safe_code: str | None,
    event_time: datetime,
    include_outbound: bool,
) -> FollowUpTaskEvent:
    idempotency_key = f"worker:{task.state_version}:{to_status}"
    command = {
        "from_status": from_status,
        "safe_code": safe_code,
        "state_version": task.state_version,
        "task_id": str(task.id),
        "to_status": to_status,
    }
    command_hash = hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return FollowUpTaskEvent(
        id=uuid.uuid5(task.id, f"follow-up-event:{idempotency_key}"),
        task_id=task.id,
        opportunity_id=task.opportunity_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        state_version=task.state_version,
        actor_type="worker",
        actor_agent_id=None,
        actor_admin_id=None,
        actor_worker_id=worker_id,
        routing_agent_id=routing_agent_id,
        automation_agent_id=task.assigned_agent_id,
        target_channel=task.target_channel,
        control_version=task.scheduled_control_version,
        automation_version=task.scheduled_automation_version,
        scheduled_policy_version=task.scheduled_policy_version,
        executed_policy_version=task.executed_policy_version,
        consent_record_id=task.consent_record_id,
        executed_consent_record_id=task.executed_consent_record_id,
        caused_by_consent_record_id=None,
        chat_message_id=task.chat_message_id,
        outbound_message_id=(task.outbound_message_id if include_outbound else None),
        safe_code=safe_code,
        correlation_id=task.correlation_id,
        idempotency_key=idempotency_key,
        command_hash=command_hash,
        created_at=event_time,
    )


def _worker_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise ValueError("invalid follow-up worker id")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("follow-up timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _phone_digits(value: str) -> str:
    return _PHONE_DIGITS.sub("", value)


follow_up_execution_service = FollowUpExecutionService()
