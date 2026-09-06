"""Cooperative polling loop for durable web-chat executions."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import uuid
from datetime import timedelta

from sqlalchemy import text

from app.config import settings
from app.core.database import engine
from app.core.logging import setup_logging
from app.services.web_execution_runner import WebExecutionRunner

logger = logging.getLogger(__name__)

_REQUIRED_SCHEMA_COLUMNS = {
    "chat_conversations": {"id", "next_event_sequence"},
    "chat_executions": {
        "id",
        "conversation_id",
        "client_message_id",
        "input_hash",
        "queue_sequence",
        "attempt_count",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "control_version",
        "status",
    },
    "conversation_events": {
        "id",
        "conversation_id",
        "agent_id",
        "sequence",
        "event_type",
        "visibility",
        "payload_json",
        "created_at",
    },
}


class WebExecutionWorker:
    """Poll one configured runner with bounded failure backoff."""

    def __init__(
        self,
        runner: WebExecutionRunner,
        *,
        poll_seconds: float,
        max_backoff_seconds: float,
    ) -> None:
        if poll_seconds <= 0 or max_backoff_seconds < poll_seconds:
            raise ValueError("invalid web execution worker timing")
        self._runner = runner
        self._poll_seconds = poll_seconds
        self._max_backoff_seconds = max_backoff_seconds

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        delay = self._poll_seconds
        logger.info("web_execution_worker_started")
        try:
            while not stop_event.is_set():
                try:
                    processed = await self._runner.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "web_execution_worker_iteration_failed",
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
            logger.info("web_execution_worker_stopped")

    @staticmethod
    async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            return


async def check_worker_health() -> None:
    """Verify the durable web execution schema without calling providers."""
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
                    "('chat_conversations', 'chat_executions', "
                    "'conversation_events')"
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
                    f"Durable web execution schema is unavailable: {table_name}"
                )

        await connection.execute(text("SELECT 1 FROM conversation_events LIMIT 0"))
        await connection.execute(text("SELECT 1 FROM chat_executions LIMIT 0"))


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
    worker_id = f"{settings.web_execution_worker_id}:{uuid.uuid4()}"
    runner = WebExecutionRunner(
        worker_id=worker_id,
        lease_duration=timedelta(seconds=settings.web_execution_lease_seconds),
    )
    worker = WebExecutionWorker(
        runner,
        poll_seconds=settings.web_execution_worker_poll_seconds,
        max_backoff_seconds=settings.web_execution_worker_max_backoff_seconds,
    )
    await worker.run_forever(stop_event)


def main() -> None:
    setup_logging()
    if "--healthcheck" in sys.argv[1:]:
        try:
            asyncio.run(_run_healthcheck())
        except Exception as exc:
            logger.error(
                "web_execution_worker_healthcheck_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise SystemExit(1) from exc
        return
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
