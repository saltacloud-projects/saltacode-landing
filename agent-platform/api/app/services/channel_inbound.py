"""Durable fail-closed ingress for authenticated external channel adapters."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.channel_inbound import ChannelInboundEvent, ChannelInboundJob
from app.models.platform import ChatConversation
from app.schemas.inbound import InboundMessageEnvelope
from app.services.agent_runtime import AgentRuntimeUnavailable, agent_runtime_resolver
from app.services.channel_catalog import (
    ChannelAdapterSpec,
    require_implemented_adapter,
)
from app.services.chat_application import WhatsAppAutomationBlockedError
from app.services.conversation_control import (
    AutomationBlockedError,
    ControlVersionConflictError,
)
from app.services.inbound import dump_inbound_payload, load_inbound_payload
from app.services.inbound_crypto import InboundCryptoError, inbound_payload_crypto
from app.services.pipeline import pipeline_service
from app.services.whatsapp import whatsapp_service

logger = logging.getLogger(__name__)

_EXTERNAL_CHANNELS = {
    "whatsapp",
    "email",
    "instagram_dm",
    "facebook_messenger",
}
_FIFO_BLOCKING_STATUSES = {"queued", "processing", "review_required"}
_ZERO_EFFECT_PHASES = {"accepted", "legacy_quarantined", "claimed", "inbound_recorded"}
_TERMINAL_STATUSES = {"completed", "routed_to_human", "ignored", "cancelled"}


class ChannelInboundUnavailable(RuntimeError):
    """An authenticated webhook batch could not be durably accepted."""


class ChannelInboundOwnershipLost(RuntimeError):
    """A worker no longer owns the expected CAS/lease."""


@dataclass(frozen=True, slots=True)
class ChannelInboundBatchResult:
    accepted_job_ids: tuple[uuid.UUID, ...]
    duplicate_count: int


class ChannelInboundService:
    """Persist one authenticated provider batch in a single transaction."""

    async def enqueue_batch(
        self,
        db: AsyncSession,
        *,
        messages: list[InboundMessageEnvelope],
        route: ChannelAgentRoute,
        connection: ChannelConnection,
        adapter: ChannelAdapterSpec,
    ) -> ChannelInboundBatchResult:
        if not messages:
            return ChannelInboundBatchResult((), 0)
        if route.channel == "web" or route.channel not in _EXTERNAL_CHANNELS:
            raise ValueError("durable external ingress does not accept web chat")
        if not adapter.is_implemented or adapter.channel != route.channel:
            raise ValueError("channel adapter is not executable")
        if (
            route.channel_connection_id != connection.id
            or route.agent_id is None
            or connection.channel != route.channel
            or connection.adapter_key != adapter.adapter_key
        ):
            raise ValueError("channel route snapshot is inconsistent")

        rows: list[dict] = []
        for message in messages:
            self._assert_message_snapshot(message, route, connection)
            payload = dump_inbound_payload(message)
            try:
                protected = inbound_payload_crypto.protect(payload)
            except InboundCryptoError as exc:
                raise ChannelInboundUnavailable(
                    "authenticated channel batch could not be protected"
                ) from exc
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "channel": route.channel,
                    "adapter_key": adapter.adapter_key,
                    "adapter_version": adapter.version,
                    "channel_route_id": route.id,
                    "channel_route_version": route.version,
                    "route_key_snapshot": route.route_key,
                    "channel_connection_id": connection.id,
                    "channel_connection_version": connection.version,
                    "routing_agent_id": route.agent_id,
                    "provider_message_id": message.provider_message_id,
                    "thread_key": inbound_payload_crypto.thread_key(
                        channel=route.channel,
                        route_id=str(route.id),
                        thread_id=message.provider_thread_id,
                    ),
                    "payload_ciphertext": protected.ciphertext,
                    "payload_hash": protected.integrity_hash,
                    "legacy_payload_json": None,
                    "status": "queued",
                    "phase": "accepted",
                    "state_version": 0,
                    "attempts": 0,
                    "legacy_max_attempts": 1,
                }
            )

        statement = (
            insert(ChannelInboundJob)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["channel_route_id", "provider_message_id"]
            )
            .returning(ChannelInboundJob.id)
        )
        try:
            inserted_ids = tuple((await db.execute(statement)).scalars().all())
            inserted_set = set(inserted_ids)
            for row in rows:
                if row["id"] in inserted_set:
                    db.add(
                        self._event_from_snapshot(
                            row,
                            event_type="accepted",
                            from_status=None,
                            actor_type="system",
                        )
                    )
            await db.commit()
        except (SQLAlchemyError, InboundCryptoError) as exc:
            await db.rollback()
            raise ChannelInboundUnavailable(
                "authenticated channel batch could not be persisted"
            ) from exc
        return ChannelInboundBatchResult(
            accepted_job_ids=inserted_ids,
            duplicate_count=len(rows) - len(inserted_ids),
        )

    @staticmethod
    def _assert_message_snapshot(
        message: InboundMessageEnvelope,
        route: ChannelAgentRoute,
        connection: ChannelConnection,
    ) -> None:
        if (
            message.channel != route.channel
            or message.route.route_key != route.route_key
            or message.route.channel_route_id != route.id
            or message.route.channel_connection_id != connection.id
        ):
            raise ValueError("inbound message does not match its authenticated route")

    @staticmethod
    def _event_from_snapshot(
        snapshot: dict,
        *,
        event_type: str,
        from_status: str | None,
        actor_type: str,
    ) -> ChannelInboundEvent:
        return ChannelInboundEvent(
            job_id=snapshot["id"],
            event_type=event_type,
            from_status=from_status,
            to_status=snapshot["status"],
            state_version=snapshot["state_version"],
            phase=snapshot["phase"],
            actor_type=actor_type,
            channel=snapshot["channel"],
            adapter_key=snapshot["adapter_key"],
            adapter_version=snapshot["adapter_version"],
            channel_route_id=snapshot["channel_route_id"],
            channel_route_version=snapshot["channel_route_version"],
            channel_connection_id=snapshot["channel_connection_id"],
            channel_connection_version=snapshot["channel_connection_version"],
            routing_agent_id=snapshot["routing_agent_id"],
            evidence_json={},
        )


class ChannelInboundLifecycleRecorder:
    """Persist execution fences using an independent short transaction."""

    def __init__(self, *, job_id: uuid.UUID, worker_id: str) -> None:
        self._job_id = job_id
        self._worker_id = worker_id

    async def inbound_recorded(
        self,
        *,
        conversation_id: uuid.UUID,
        control_version: int,
        automation_agent_id: uuid.UUID,
        automation_version: int,
    ) -> None:
        await self._advance(
            phase="inbound_recorded",
            conversation_id=conversation_id,
            control_version=control_version,
            automation_agent_id=automation_agent_id,
            automation_version=automation_version,
        )

    async def before_external_effect(self, *, phase: str) -> None:
        if phase not in {
            "provider_effect_started",
            "transcription_started",
            "agent_effect_started",
            "outbox_effect_started",
        }:
            raise ValueError("unsupported inbound lifecycle phase")
        await self._advance(phase=phase)

    async def _advance(
        self,
        *,
        phase: str,
        conversation_id: uuid.UUID | None = None,
        control_version: int | None = None,
        automation_agent_id: uuid.UUID | None = None,
        automation_version: int | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await _owned_processing_job(
                    db, job_id=self._job_id, worker_id=self._worker_id
                )
                if conversation_id is not None:
                    job.conversation_id = conversation_id
                    job.conversation_control_version = control_version
                    job.automation_agent_id = automation_agent_id
                    job.conversation_automation_version = automation_version
                from_status = job.status
                job.phase = phase
                job.state_version += 1
                db.add(
                    build_channel_inbound_event(
                        job,
                        event_type="phase_advanced",
                        from_status=from_status,
                        actor_type="worker",
                    )
                )


class ChannelInboundWorker:
    """Claim one strict-FIFO external ingress job without automatic retries."""

    def __init__(self) -> None:
        self._worker_id = f"{settings.channel_inbound_worker_id}:{uuid.uuid4()}"

    async def run_forever(self) -> None:
        redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        logger.info("channel_inbound_worker_started")
        try:
            while True:
                try:
                    processed = await self.run_once(redis)
                except Exception:
                    logger.exception("channel_inbound_worker_iteration_failed")
                    processed = False
                if not processed:
                    await asyncio.sleep(settings.channel_inbound_poll_seconds)
        finally:
            await redis.aclose()
            await engine.dispose()

    async def run_once(self, redis) -> bool:
        async with AsyncSessionLocal() as db:
            job_id = await self._claim_job(db)
        if job_id is None:
            return False
        try:
            await self._process_job(job_id, redis)
            if not await self._execution_epoch_is_current(job_id):
                await self._transition_owned(
                    job_id,
                    status="review_required",
                    event_type="review_required",
                    safe_code="conversation_epoch_changed",
                )
            else:
                await self._transition_owned(
                    job_id,
                    status="completed",
                    event_type="completed",
                )
        except (
            AutomationBlockedError,
            ControlVersionConflictError,
            WhatsAppAutomationBlockedError,
        ):
            phase = await self._current_phase(job_id)
            if phase in _ZERO_EFFECT_PHASES:
                await self._transition_owned(
                    job_id,
                    status="routed_to_human",
                    event_type="routed_to_human",
                    safe_code="automation_not_owner",
                )
            else:
                await self._transition_owned(
                    job_id,
                    status="review_required",
                    event_type="review_required",
                    safe_code="ownership_changed_after_effect",
                )
        except Exception as exc:
            logger.error(
                "channel_inbound_job_review_required",
                extra={"job_id": str(job_id), "error_type": type(exc).__name__},
            )
            await self._transition_owned(
                job_id,
                status="review_required",
                event_type="review_required",
                safe_code=_safe_error_code(exc),
            )
        return True

    async def _claim_job(self, db: AsyncSession) -> uuid.UUID | None:
        now = datetime.now(timezone.utc)
        async with db.begin():
            expired = (
                (
                    await db.execute(
                        select(ChannelInboundJob)
                        .where(
                            ChannelInboundJob.status == "processing",
                            ChannelInboundJob.lease_expires_at < now,
                        )
                        .order_by(ChannelInboundJob.lease_expires_at)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if expired is not None:
                _transition(
                    expired,
                    status="review_required",
                    phase=expired.phase,
                    event_type="review_required",
                    safe_code="lease_expired",
                    actor_type="system",
                    db=db,
                )
                return None

            earlier = aliased(ChannelInboundJob)
            has_earlier_blocker = exists(
                select(1).where(
                    earlier.thread_key == ChannelInboundJob.thread_key,
                    earlier.status.in_(_FIFO_BLOCKING_STATUSES),
                    or_(
                        earlier.created_at < ChannelInboundJob.created_at,
                        and_(
                            earlier.created_at == ChannelInboundJob.created_at,
                            earlier.id < ChannelInboundJob.id,
                        ),
                    ),
                )
            )
            job = (
                (
                    await db.execute(
                        select(ChannelInboundJob)
                        .where(
                            ChannelInboundJob.status == "queued",
                            ChannelInboundJob.thread_key.is_not(None),
                            ~has_earlier_blocker,
                        )
                        .order_by(ChannelInboundJob.created_at, ChannelInboundJob.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if job is None:
                return None
            job.status = "processing"
            job.phase = "claimed"
            job.state_version += 1
            job.attempts += 1
            job.lease_owner = self._worker_id
            job.lease_expires_at = now + timedelta(
                seconds=settings.channel_inbound_lease_seconds
            )
            job.safe_code = None
            db.add(
                build_channel_inbound_event(
                    job,
                    event_type="claimed",
                    from_status="queued",
                    actor_type="worker",
                )
            )
            return job.id

    async def _process_job(self, job_id: uuid.UUID, redis) -> None:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(ChannelInboundJob, ChannelAgentRoute, ChannelConnection)
                    .join(
                        ChannelAgentRoute,
                        ChannelAgentRoute.id == ChannelInboundJob.channel_route_id,
                    )
                    .join(
                        ChannelConnection,
                        ChannelConnection.id == ChannelInboundJob.channel_connection_id,
                    )
                    .where(
                        ChannelInboundJob.id == job_id,
                        ChannelInboundJob.status == "processing",
                        ChannelInboundJob.lease_owner == self._worker_id,
                    )
                )
            ).one_or_none()
            if row is None:
                raise ChannelInboundOwnershipLost("channel ingress ownership was lost")
            job, route, connection = row
            adapter = require_implemented_adapter(
                channel=job.channel, adapter_key=job.adapter_key
            )
            self._assert_route_snapshot(job, route, connection, adapter)
            if job.channel != "whatsapp":
                raise AgentRuntimeUnavailable(
                    "channel adapter execution is unavailable"
                )
            if job.legacy_payload_json is not None:
                raise InboundCryptoError("legacy inbound payload remains quarantined")
            if not job.payload_ciphertext or not job.payload_hash:
                raise InboundCryptoError("encrypted inbound payload is unavailable")
            payload = inbound_payload_crypto.reveal(
                ciphertext=job.payload_ciphertext,
                integrity_hash=job.payload_hash,
            )
            message = load_inbound_payload(
                payload,
                channel=job.channel,
                route_key=job.route_key_snapshot,
                channel_route_id=job.channel_route_id,
                channel_connection_id=job.channel_connection_id,
                provider_message_id=job.provider_message_id,
                fallback_correlation_id=job.id,
                fallback_timestamp=job.created_at,
            )
            runtime = await agent_runtime_resolver.resolve_agent(
                db, job.routing_agent_id, require_public=False
            )
            whatsapp_connection = whatsapp_service.resolve_connection(
                connection, route_key=job.route_key_snapshot
            )

        lifecycle = ChannelInboundLifecycleRecorder(
            job_id=job_id, worker_id=self._worker_id
        )
        await pipeline_service.process_whatsapp_message(
            message=message,
            redis=redis,
            resolved_runtime=runtime,
            whatsapp_connection=whatsapp_connection,
            request_id=str(message.correlation_id),
            propagate_errors=True,
            notify_on_error=False,
            lock_subject=job.thread_key,
            lifecycle=lifecycle,
        )

    @staticmethod
    def _assert_route_snapshot(
        job: ChannelInboundJob,
        route: ChannelAgentRoute,
        connection: ChannelConnection,
        adapter: ChannelAdapterSpec,
    ) -> None:
        current = (
            route.channel,
            route.version,
            route.route_key,
            route.channel_connection_id,
            route.agent_id,
            route.is_active,
            connection.channel,
            connection.version,
            connection.adapter_key,
            connection.is_active,
            adapter.version,
        )
        snapshot = (
            job.channel,
            job.channel_route_version,
            job.route_key_snapshot,
            job.channel_connection_id,
            job.routing_agent_id,
            True,
            job.channel,
            job.channel_connection_version,
            job.adapter_key,
            True,
            job.adapter_version,
        )
        if current != snapshot:
            raise AgentRuntimeUnavailable("channel route snapshot changed")

    async def _execution_epoch_is_current(self, job_id: uuid.UUID) -> bool:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(ChannelInboundJob, ChatConversation)
                    .outerjoin(
                        ChatConversation,
                        ChatConversation.id == ChannelInboundJob.conversation_id,
                    )
                    .where(ChannelInboundJob.id == job_id)
                )
            ).one_or_none()
            if row is None:
                return False
            job, conversation = row
            if conversation is None:
                return job.phase in {"accepted", "claimed"}
            return (
                conversation.control_mode == "automated"
                and conversation.control_version == job.conversation_control_version
                and conversation.automation_agent_id == job.automation_agent_id
                and conversation.automation_version
                == job.conversation_automation_version
            )

    async def _current_phase(self, job_id: uuid.UUID) -> str:
        async with AsyncSessionLocal() as db:
            phase = (
                await db.execute(
                    select(ChannelInboundJob.phase).where(
                        ChannelInboundJob.id == job_id
                    )
                )
            ).scalar_one_or_none()
        return phase or "accepted"

    async def _transition_owned(
        self,
        job_id: uuid.UUID,
        *,
        status: str,
        event_type: str,
        safe_code: str | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await _owned_processing_job(
                    db, job_id=job_id, worker_id=self._worker_id
                )
                _transition(
                    job,
                    status=status,
                    phase="terminal" if status in _TERMINAL_STATUSES else job.phase,
                    event_type=event_type,
                    safe_code=safe_code,
                    actor_type="worker",
                    db=db,
                )


async def _owned_processing_job(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    worker_id: str,
) -> ChannelInboundJob:
    job = (
        (
            await db.execute(
                select(ChannelInboundJob)
                .where(
                    ChannelInboundJob.id == job_id,
                    ChannelInboundJob.status == "processing",
                    ChannelInboundJob.lease_owner == worker_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .one_or_none()
    )
    if job is None:
        raise ChannelInboundOwnershipLost("channel ingress ownership was lost")
    return job


def _transition(
    job: ChannelInboundJob,
    *,
    status: str,
    phase: str,
    event_type: str,
    safe_code: str | None,
    actor_type: str,
    db: AsyncSession,
) -> None:
    from_status = job.status
    job.status = status
    job.phase = phase
    job.state_version += 1
    job.safe_code = safe_code
    job.lease_owner = None
    job.lease_expires_at = None
    if status in _TERMINAL_STATUSES:
        job.payload_ciphertext = None
        job.payload_hash = None
        job.legacy_payload_json = None
        job.terminal_at = datetime.now(timezone.utc)
    db.add(
        build_channel_inbound_event(
            job,
            event_type=event_type,
            from_status=from_status,
            actor_type=actor_type,
        )
    )


def build_channel_inbound_event(
    job: ChannelInboundJob,
    *,
    event_type: str,
    from_status: str | None,
    actor_type: str,
    actor_admin_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    command_hash: str | None = None,
    correlation_id: str | None = None,
) -> ChannelInboundEvent:
    return ChannelInboundEvent(
        job_id=job.id,
        event_type=event_type,
        from_status=from_status,
        to_status=job.status,
        state_version=job.state_version,
        phase=job.phase,
        actor_type=actor_type,
        actor_admin_id=actor_admin_id,
        safe_code=job.safe_code,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        command_hash=command_hash,
        channel=job.channel,
        adapter_key=job.adapter_key,
        adapter_version=job.adapter_version,
        channel_route_id=job.channel_route_id,
        channel_route_version=job.channel_route_version,
        channel_connection_id=job.channel_connection_id,
        channel_connection_version=job.channel_connection_version,
        routing_agent_id=job.routing_agent_id,
        conversation_id=job.conversation_id,
        conversation_control_version=job.conversation_control_version,
        automation_agent_id=job.automation_agent_id,
        conversation_automation_version=job.conversation_automation_version,
        evidence_json={},
    )


def command_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, AgentRuntimeUnavailable):
        return "route_snapshot_changed"
    if isinstance(exc, InboundCryptoError):
        return "payload_unavailable"
    return f"processing_{type(exc).__name__}"[:80]


channel_inbound_service = ChannelInboundService()
channel_inbound_worker = ChannelInboundWorker()
