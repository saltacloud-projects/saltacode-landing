"""Cooperative worker for durable commercial follow-up execution."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.logging import setup_logging
from app.services.commercial.follow_up_execution import (
    ClaimedFollowUp,
    FollowUpExecutionService,
    follow_up_execution_service,
)

logger = logging.getLogger(__name__)

_REQUIRED_SCHEMA_COLUMNS = {
    "commercial_automation_policies": {
        "agent_id",
        "is_enabled",
        "allowed_kinds",
        "timezone",
        "version",
    },
    "follow_up_task_events": {
        "task_id",
        "state_version",
        "to_status",
        "actor_worker_id",
        "safe_code",
    },
    "follow_up_tasks": {
        "id",
        "status",
        "fifo_key",
        "available_at",
        "attempts",
        "lease_owner",
        "lease_expires_at",
        "outbound_message_id",
    },
    "outbound_messages": {"id", "status"},
}


class FollowUpExecutionRunner:
    """Coordinate short transactions around one committed follow-up claim."""

    def __init__(
        self,
        *,
        worker_id: str,
        lease_duration: timedelta,
        execution: FollowUpExecutionService = follow_up_execution_service,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("follow-up lease duration must be positive")
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._execution = execution
        self._session_factory = session_factory

    async def run_once(self) -> bool:
        claim: ClaimedFollowUp | None = None
        async with self._session_factory() as db:
            async with db.begin():
                recovered = await self._execution.recover_expired_leases(
                    db,
                    worker_id=self._worker_id,
                )
                reconciled = await self._execution.reconcile_next(
                    db,
                    worker_id=self._worker_id,
                )
                if reconciled.processed:
                    return True
                claim = await self._execution.claim_next(
                    db,
                    worker_id=self._worker_id,
                    lease_duration=self._lease_duration,
                )
                if claim is None:
                    return recovered > 0

        try:
            async with self._session_factory() as db:
                async with db.begin():
                    await self._execution.enqueue_claim(db, claim=claim)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "follow_up_execution_failed",
                extra={
                    "task_id": str(claim.task_id),
                    "error_type": type(exc).__name__,
                },
            )
            async with self._session_factory() as db:
                async with db.begin():
                    await self._execution.mark_claim_error_for_review(
                        db,
                        claim=claim,
                    )
        return True


class FollowUpWorker:
    """Poll one follow-up runner with bounded failure backoff."""

    def __init__(
        self,
        runner: FollowUpExecutionRunner,
        *,
        poll_seconds: float,
        max_backoff_seconds: float,
    ) -> None:
        if poll_seconds <= 0 or max_backoff_seconds < poll_seconds:
            raise ValueError("invalid follow-up worker timing")
        self._runner = runner
        self._poll_seconds = poll_seconds
        self._max_backoff_seconds = max_backoff_seconds

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        delay = self._poll_seconds
        logger.info("follow_up_worker_started")
        try:
            while not stop_event.is_set():
                try:
                    processed = await self._runner.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "follow_up_worker_iteration_failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    delay = min(
                        self._max_backoff_seconds,
                        max(self._poll_seconds, delay * 2),
                    )
                else:
                    delay = self._poll_seconds
                    if processed:
                        continue
                await self._wait_or_stop(stop_event, delay)
        finally:
            await engine.dispose()
            logger.info("follow_up_worker_stopped")

    @staticmethod
    async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            return


async def check_worker_health() -> None:
    """Verify follow-up execution schema without contacting providers."""

    async with engine.connect() as connection:
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        if not revision:
            raise RuntimeError("Alembic revision is unavailable")
        rows = (
            await connection.execute(
                text(
                    "SELECT table_name, column_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name IN "
                    "('commercial_automation_policies', "
                    "'follow_up_task_events', 'follow_up_tasks', "
                    "'outbound_messages')"
                )
            )
        ).all()
        available = {table: set() for table in _REQUIRED_SCHEMA_COLUMNS}
        for table_name, column_name in rows:
            if table_name in available:
                available[table_name].add(column_name)
        for table_name, required_columns in _REQUIRED_SCHEMA_COLUMNS.items():
            if not required_columns.issubset(available[table_name]):
                raise RuntimeError(
                    f"Follow-up execution schema is unavailable: {table_name}"
                )
        await connection.execute(text("SELECT 1 FROM follow_up_tasks LIMIT 0"))


async def _run_healthcheck() -> None:
    try:
        await check_worker_health()
    finally:
        await engine.dispose()


async def _run_worker() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop_event.set)
    worker_id = f"{settings.follow_up_worker_id}:{uuid.uuid4()}"
    runner = FollowUpExecutionRunner(
        worker_id=worker_id,
        lease_duration=timedelta(seconds=settings.follow_up_execution_lease_seconds),
    )
    worker = FollowUpWorker(
        runner,
        poll_seconds=settings.follow_up_worker_poll_seconds,
        max_backoff_seconds=settings.follow_up_worker_max_backoff_seconds,
    )
    await worker.run_forever(stop_event)


def main() -> None:
    setup_logging()
    if "--healthcheck" in sys.argv[1:]:
        try:
            asyncio.run(_run_healthcheck())
        except Exception as exc:
            logger.error(
                "follow_up_worker_healthcheck_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise SystemExit(1) from exc
        return
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
