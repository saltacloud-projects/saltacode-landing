"""Agent-scoped read and semantic review commands for external ingress."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_inbound import ChannelInboundEvent, ChannelInboundJob
from app.schemas.channel_inbound import (
    ChannelInboundDetailOut,
    ChannelInboundEventOut,
    ChannelInboundSummaryOut,
)
from app.services.channel_inbound import build_channel_inbound_event, command_hash
from app.services.inbound import dump_inbound_payload, load_inbound_payload
from app.services.inbound_crypto import inbound_payload_crypto

_REQUEUE_PHASES = {"accepted", "legacy_quarantined", "claimed"}


class ChannelInboundReviewError(Exception):
    """Base error for privacy-safe ingress review."""


class ChannelInboundNotFound(ChannelInboundReviewError):
    """The job does not exist in the requested agent scope."""


class ChannelInboundVersionConflict(ChannelInboundReviewError):
    """The caller acted on an obsolete job state."""


class ChannelInboundIdempotencyConflict(ChannelInboundReviewError):
    """An idempotency key was reused with different command semantics."""


class InvalidChannelInboundCommand(ChannelInboundReviewError):
    """The requested review resolution violates ingress invariants."""


@dataclass(frozen=True, slots=True)
class ChannelInboundPage:
    items: list[ChannelInboundSummaryOut]
    total: int


class ChannelInboundReviewService:
    async def list_jobs(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> ChannelInboundPage:
        predicates = [ChannelInboundJob.routing_agent_id == agent_id]
        if status is not None:
            predicates.append(ChannelInboundJob.status == status)
        total = (
            await db.execute(
                select(func.count(ChannelInboundJob.id)).where(*predicates)
            )
        ).scalar_one()
        jobs = (
            (
                await db.execute(
                    select(ChannelInboundJob)
                    .where(*predicates)
                    .order_by(
                        ChannelInboundJob.updated_at.desc(),
                        ChannelInboundJob.id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return ChannelInboundPage(
            items=[self._summary(job) for job in jobs],
            total=total,
        )

    async def get_job(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> ChannelInboundDetailOut:
        job = await self._get(db, agent_id=agent_id, job_id=job_id)
        return ChannelInboundDetailOut(
            **self._summary(job).model_dump(),
            routing_agent_id=job.routing_agent_id,
            conversation_control_version=job.conversation_control_version,
            automation_agent_id=job.automation_agent_id,
            conversation_automation_version=job.conversation_automation_version,
            legacy_payload_quarantined=job.legacy_payload_json is not None,
        )

    async def timeline(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> list[ChannelInboundEventOut]:
        await self._get(db, agent_id=agent_id, job_id=job_id)
        events = (
            (
                await db.execute(
                    select(ChannelInboundEvent)
                    .where(ChannelInboundEvent.job_id == job_id)
                    .order_by(
                        ChannelInboundEvent.state_version,
                        ChannelInboundEvent.created_at,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            ChannelInboundEventOut(
                id=event.id,
                event_type=event.event_type,
                from_status=event.from_status,
                to_status=event.to_status,
                state_version=event.state_version,
                phase=event.phase,
                actor_type=event.actor_type,
                has_actor_admin=event.actor_admin_id is not None,
                safe_code=event.safe_code,
                created_at=event.created_at,
            )
            for event in events
        ]

    async def requeue(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        job_id: uuid.UUID,
        admin_id: uuid.UUID,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str,
    ) -> ChannelInboundJob:
        job, replayed = await self._command_context(
            db,
            agent_id=agent_id,
            job_id=job_id,
            expected_version=expected_version,
            action="requeue",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if replayed:
            return job
        if job.status != "review_required" or job.phase not in _REQUEUE_PHASES:
            raise InvalidChannelInboundCommand(
                "inbound job cannot be requeued after an external effect"
            )
        if job.legacy_payload_json is not None:
            message = load_inbound_payload(
                dict(job.legacy_payload_json),
                channel=job.channel,
                route_key=job.route_key_snapshot,
                channel_route_id=job.channel_route_id,
                channel_connection_id=job.channel_connection_id,
                provider_message_id=job.provider_message_id,
                fallback_correlation_id=job.id,
                fallback_timestamp=job.created_at,
            )
            protected = inbound_payload_crypto.protect(dump_inbound_payload(message))
            job.payload_ciphertext = protected.ciphertext
            job.payload_hash = protected.integrity_hash
            job.thread_key = inbound_payload_crypto.thread_key(
                channel=job.channel,
                route_id=str(job.channel_route_id),
                thread_id=message.provider_thread_id,
            )
            job.legacy_payload_json = None
        if not job.payload_ciphertext or not job.payload_hash or not job.thread_key:
            raise InvalidChannelInboundCommand(
                "inbound payload cannot be made executable"
            )
        await self._apply_command(
            db,
            job=job,
            admin_id=admin_id,
            status="queued",
            phase="accepted",
            event_type="requeued",
            safe_code=None,
            action="requeue",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return job

    async def cancel(
        self,
        db: AsyncSession,
        **kwargs,
    ) -> ChannelInboundJob:
        return await self._terminal_command(
            db,
            action="cancel",
            status="cancelled",
            event_type="cancelled",
            allowed={"queued", "review_required"},
            **kwargs,
        )

    async def acknowledge(
        self,
        db: AsyncSession,
        **kwargs,
    ) -> ChannelInboundJob:
        return await self._terminal_command(
            db,
            action="acknowledge",
            status="ignored",
            event_type="acknowledged",
            allowed={"review_required"},
            **kwargs,
        )

    async def _terminal_command(
        self,
        db: AsyncSession,
        *,
        action: str,
        status: str,
        event_type: str,
        allowed: set[str],
        agent_id: uuid.UUID,
        job_id: uuid.UUID,
        admin_id: uuid.UUID,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str,
    ) -> ChannelInboundJob:
        job, replayed = await self._command_context(
            db,
            agent_id=agent_id,
            job_id=job_id,
            expected_version=expected_version,
            action=action,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if replayed:
            return job
        if job.status not in allowed:
            raise InvalidChannelInboundCommand(
                f"inbound job cannot be resolved with {action}"
            )
        await self._apply_command(
            db,
            job=job,
            admin_id=admin_id,
            status=status,
            phase="terminal",
            event_type=event_type,
            safe_code=action,
            action=action,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        job.payload_ciphertext = None
        job.payload_hash = None
        job.legacy_payload_json = None
        return job

    async def _command_context(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        job_id: uuid.UUID,
        expected_version: int,
        action: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> tuple[ChannelInboundJob, bool]:
        normalized_key = idempotency_key.strip()
        normalized_correlation = correlation_id.strip()
        if not normalized_key or not normalized_correlation:
            raise InvalidChannelInboundCommand(
                "idempotency and correlation identifiers are required"
            )
        digest = command_hash(
            {
                "action": action,
                "expected_version": expected_version,
                "job_id": str(job_id),
            }
        )
        job = (
            await db.execute(
                select(ChannelInboundJob)
                .where(
                    ChannelInboundJob.id == job_id,
                    ChannelInboundJob.routing_agent_id == agent_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            raise ChannelInboundNotFound("inbound job not found")
        existing = (
            await db.execute(
                select(ChannelInboundEvent).where(
                    ChannelInboundEvent.job_id == job.id,
                    ChannelInboundEvent.idempotency_key == normalized_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.command_hash != digest:
                raise ChannelInboundIdempotencyConflict(
                    "inbound idempotency key collision"
                )
            return job, True
        if job.state_version != expected_version:
            raise ChannelInboundVersionConflict("inbound state version conflict")
        return job, False

    async def _apply_command(
        self,
        db: AsyncSession,
        *,
        job: ChannelInboundJob,
        admin_id: uuid.UUID,
        status: str,
        phase: str,
        event_type: str,
        safe_code: str | None,
        action: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> None:
        from_status = job.status
        job.status = status
        job.phase = phase
        job.safe_code = safe_code
        job.state_version += 1
        job.lease_owner = None
        job.lease_expires_at = None
        if status in {"cancelled", "ignored"}:
            job.terminal_at = datetime.now(timezone.utc)
        digest = command_hash(
            {
                "action": action,
                "expected_version": job.state_version - 1,
                "job_id": str(job.id),
            }
        )
        db.add(
            build_channel_inbound_event(
                job,
                event_type=event_type,
                from_status=from_status,
                actor_type="operator",
                actor_admin_id=admin_id,
                idempotency_key=idempotency_key.strip(),
                command_hash=digest,
                correlation_id=correlation_id.strip(),
            )
        )
        await db.flush()

    async def _get(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> ChannelInboundJob:
        job = (
            await db.execute(
                select(ChannelInboundJob).where(
                    ChannelInboundJob.id == job_id,
                    ChannelInboundJob.routing_agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise ChannelInboundNotFound("inbound job not found")
        return job

    @staticmethod
    def _summary(job: ChannelInboundJob) -> ChannelInboundSummaryOut:
        return ChannelInboundSummaryOut(
            id=job.id,
            channel=job.channel,
            adapter_key=job.adapter_key,
            adapter_version=job.adapter_version,
            channel_route_id=job.channel_route_id,
            channel_route_version=job.channel_route_version,
            channel_connection_id=job.channel_connection_id,
            channel_connection_version=job.channel_connection_version,
            status=job.status,
            phase=job.phase,
            state_version=job.state_version,
            attempts=job.attempts,
            safe_code=job.safe_code,
            conversation_id=job.conversation_id,
            created_at=job.created_at,
            updated_at=job.updated_at,
            terminal_at=job.terminal_at,
        )


channel_inbound_review_service = ChannelInboundReviewService()
