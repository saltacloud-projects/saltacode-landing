"""Durable enqueue and worker policy for route-scoped WhatsApp ingress."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.agent_runtime import ChannelAgentRoute
from app.models.whatsapp_inbox import WhatsAppInboundJob
from app.services.agent_runtime import AgentRuntimeUnavailable, agent_runtime_resolver
from app.services.pipeline import pipeline_service
from app.services.whatsapp import whatsapp_service

logger = logging.getLogger(__name__)


class WhatsAppInboxUnavailable(RuntimeError):
    """The authenticated message could not be durably accepted."""


@dataclass(frozen=True)
class WhatsAppEnqueueResult:
    job_id: uuid.UUID | None

    @property
    def duplicate(self) -> bool:
        return self.job_id is None


def minimal_inbound_payload(message: dict) -> dict:
    """Keep only fields required by the pipeline; never persist credentials."""
    return {
        "phone_number": message["phone_number"],
        "content": message["content"],
        "input_type": message["input_type"],
        "audio_media_id": message.get("audio_media_id"),
        "interactive_id": message.get("interactive_id"),
        "quoted_id": message.get("quoted_id"),
    }


class WhatsAppInboxService:
    async def enqueue(
        self,
        db: AsyncSession,
        *,
        channel_route_id: uuid.UUID,
        channel_connection_id: uuid.UUID,
        provider_message_id: str,
        message: dict,
    ) -> WhatsAppEnqueueResult:
        statement = (
            insert(WhatsAppInboundJob)
            .values(
                channel_route_id=channel_route_id,
                channel_connection_id=channel_connection_id,
                provider_message_id=provider_message_id,
                payload_json=minimal_inbound_payload(message),
                status="queued",
                attempts=0,
                max_attempts=settings.whatsapp_inbox_max_attempts,
            )
            .on_conflict_do_nothing(
                index_elements=["channel_route_id", "provider_message_id"]
            )
            .returning(WhatsAppInboundJob.id)
        )
        try:
            job_id = (await db.execute(statement)).scalar_one_or_none()
            # The webhook acknowledges only after this commit succeeds.
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            raise WhatsAppInboxUnavailable(
                "WhatsApp message could not be persisted"
            ) from exc
        return WhatsAppEnqueueResult(job_id=job_id)


class WhatsAppInboxWorker:
    """Process one eligible job at a time.

    A single instance preserves eligible-job order. Multiple replicas claim safely,
    but they can process different messages concurrently and therefore do not offer
    strict per-conversation ordering by themselves.
    """

    def __init__(self) -> None:
        # Each process needs a distinct lease owner even when replicas share the
        # configured human-readable worker name.
        self._worker_id = f"{settings.whatsapp_inbox_worker_id}:{uuid.uuid4()}"

    async def run_forever(self) -> None:
        redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        logger.info(
            "whatsapp_inbox_worker_started",
            extra={"worker_id": self._worker_id},
        )
        try:
            while True:
                try:
                    processed = await self.run_once(redis)
                except Exception:
                    logger.exception("whatsapp_inbox_worker_iteration_failed")
                    processed = False
                if not processed:
                    await asyncio.sleep(settings.whatsapp_inbox_poll_seconds)
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
        except Exception as exc:
            logger.error(
                "whatsapp_inbox_job_failed",
                extra={"job_id": str(job_id), "error_type": type(exc).__name__},
            )
            await self._persist_failure(job_id, exc)
        else:
            await self._persist_success(job_id)
        return True

    async def _claim_job(self, db: AsyncSession) -> uuid.UUID | None:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=settings.whatsapp_inbox_stale_seconds)
        async with db.begin():
            job = (
                (
                    await db.execute(
                        select(WhatsAppInboundJob)
                        .where(
                            or_(
                                and_(
                                    WhatsAppInboundJob.status == "queued",
                                    WhatsAppInboundJob.attempts
                                    < WhatsAppInboundJob.max_attempts,
                                    or_(
                                        WhatsAppInboundJob.next_attempt_at.is_(None),
                                        WhatsAppInboundJob.next_attempt_at <= now,
                                    ),
                                ),
                                and_(
                                    WhatsAppInboundJob.status == "processing",
                                    WhatsAppInboundJob.locked_at < stale_before,
                                ),
                            )
                        )
                        .order_by(WhatsAppInboundJob.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if job is None:
                return None
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.error_code = "AttemptsExhausted"
                job.error_message = "The durable inbox exhausted its attempts"
                job.payload_json = {}
                job.locked_by = None
                job.locked_at = None
                job.completed_at = now
                return None
            job.status = "processing"
            job.attempts += 1
            job.locked_by = self._worker_id
            job.locked_at = now
            job.next_attempt_at = None
            job.error_code = None
            job.error_message = None
            await db.flush()
            return job.id

    async def _process_job(self, job_id: uuid.UUID, redis) -> None:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(WhatsAppInboundJob, ChannelAgentRoute)
                    .join(
                        ChannelAgentRoute,
                        ChannelAgentRoute.id == WhatsAppInboundJob.channel_route_id,
                    )
                    .where(
                        WhatsAppInboundJob.id == job_id,
                        WhatsAppInboundJob.status == "processing",
                        WhatsAppInboundJob.locked_by == self._worker_id,
                    )
                )
            ).one_or_none()
            if row is None:
                raise RuntimeError("WhatsApp inbox job ownership was lost")
            job, stored_route = row
            resolved_route = await agent_runtime_resolver.resolve_channel_route(
                db, "whatsapp", stored_route.route_key
            )
            self._assert_route_ownership(job, stored_route, resolved_route)
            runtime = await agent_runtime_resolver.resolve_agent(
                db, resolved_route.route.agent_id, require_public=False
            )
            connection = whatsapp_service.resolve_connection(
                resolved_route.connection, route_key=stored_route.route_key
            )
            payload = dict(job.payload_json)
            notify_on_error = self._is_final_attempt(job)
            provider_message_id = job.provider_message_id
            route_key = stored_route.route_key
            channel_route_id = stored_route.id

        await pipeline_service.process_whatsapp_message(
            phone=payload["phone_number"],
            content=payload["content"],
            message_id=provider_message_id,
            input_type=payload["input_type"],
            audio_media_id=payload.get("audio_media_id"),
            interactive_id=payload.get("interactive_id"),
            quoted_id=payload.get("quoted_id"),
            redis=redis,
            resolved_runtime=runtime,
            whatsapp_connection=connection,
            route_key=route_key,
            channel_route_id=channel_route_id,
            request_id=str(job_id),
            propagate_errors=True,
            notify_on_error=notify_on_error,
        )

    async def _persist_success(self, job_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await self._owned_processing_job(db, job_id)
                job.status = "completed"
                job.payload_json = {}
                job.completed_at = datetime.now(timezone.utc)
                job.locked_by = None
                job.locked_at = None
                job.next_attempt_at = None

    async def _persist_failure(self, job_id: uuid.UUID, exc: Exception) -> None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await self._owned_processing_job(db, job_id)
                job.error_code = type(exc).__name__[:80]
                # Avoid persisting provider responses or secret-bearing exception text.
                job.error_message = f"Processing failed with {type(exc).__name__}"
                job.locked_by = None
                job.locked_at = None
                if job.attempts < job.max_attempts:
                    job.status = "queued"
                    job.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                        seconds=min(300, 2**job.attempts)
                    )
                else:
                    job.status = "failed"
                    job.payload_json = {}
                    job.completed_at = datetime.now(timezone.utc)

    @staticmethod
    def _is_final_attempt(job: WhatsAppInboundJob) -> bool:
        return job.attempts >= job.max_attempts

    @staticmethod
    def _assert_route_ownership(job, stored_route, resolved_route) -> None:
        if resolved_route.route.id != job.channel_route_id:
            raise AgentRuntimeUnavailable("channel route ownership changed")
        if (
            stored_route.channel_connection_id != job.channel_connection_id
            or resolved_route.connection.id != job.channel_connection_id
        ):
            raise AgentRuntimeUnavailable("channel connection ownership changed")

    async def _owned_processing_job(
        self, db: AsyncSession, job_id: uuid.UUID
    ) -> WhatsAppInboundJob:
        job = (
            (
                await db.execute(
                    select(WhatsAppInboundJob)
                    .where(
                        WhatsAppInboundJob.id == job_id,
                        WhatsAppInboundJob.status == "processing",
                        WhatsAppInboundJob.locked_by == self._worker_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .one_or_none()
        )
        if job is None:
            raise RuntimeError("WhatsApp inbox job ownership was lost")
        return job


whatsapp_inbox_service = WhatsAppInboxService()
whatsapp_inbox_worker = WhatsAppInboxWorker()
