"""Entrypoint for the channel-neutral outbound delivery worker."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.core.database import engine
from app.core.logging import setup_logging
from app.services.outbound_dispatcher import OutboundDispatcher
from app.services.outbound_whatsapp import whatsapp_outbound_adapter

logger = logging.getLogger(__name__)

_REQUIRED_OUTBOUND_COLUMNS = {
    "id",
    "conversation_id",
    "agent_id",
    "channel_route_id",
    "chat_message_id",
    "kind",
    "payload_json",
    "destination",
    "sender_type",
    "sender_admin_id",
    "control_version",
    "sequence",
    "idempotency_key",
    "payload_hash",
    "correlation_id",
    "status",
    "provider_message_id",
    "last_attempt_number",
    "locked_by",
    "locked_at",
    "accepted_at",
    "delivered_at",
    "created_at",
    "updated_at",
}


class OutboundWorker:
    """Poll outbound work with bounded failure backoff and cooperative shutdown."""

    def __init__(self, dispatcher: OutboundDispatcher) -> None:
        self._dispatcher = dispatcher

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        delay = settings.outbound_worker_poll_seconds
        logger.info("outbound_worker_started")
        try:
            while not stop_event.is_set():
                try:
                    processed = await self._dispatcher.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "outbound_worker_iteration_failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    delay = min(
                        settings.outbound_worker_max_backoff_seconds,
                        max(settings.outbound_worker_poll_seconds, delay * 2),
                    )
                else:
                    delay = settings.outbound_worker_poll_seconds
                    if processed:
                        continue
                await self._wait_or_stop(stop_event, delay)
        finally:
            await engine.dispose()
            logger.info("outbound_worker_stopped")

    @staticmethod
    async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            return


async def check_worker_health() -> None:
    """Verify database reachability, schema availability, and local storage."""
    async with engine.connect() as connection:
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        if not revision:
            raise RuntimeError("Alembic revision is unavailable")
        columns = set(
            (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'outbound_messages'"
                    )
                )
            )
            .scalars()
            .all()
        )
        if not _REQUIRED_OUTBOUND_COLUMNS.issubset(columns):
            raise RuntimeError("Outbound delivery migration is unavailable")
        await connection.execute(text("SELECT 1 FROM outbound_messages LIMIT 0"))
    storage_root = Path(settings.document_storage_root).resolve()
    if not storage_root.is_dir() or not os.access(storage_root, os.R_OK):
        raise RuntimeError("Outbound document storage is unavailable")


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
    worker_id = f"{settings.outbound_worker_id}:{uuid.uuid4()}"
    dispatcher = OutboundDispatcher(
        worker_id=worker_id,
        stale_seconds=settings.outbound_dispatch_stale_seconds,
        adapters=[whatsapp_outbound_adapter],
    )
    await OutboundWorker(dispatcher).run_forever(stop_event)


def main() -> None:
    setup_logging()
    if "--healthcheck" in sys.argv[1:]:
        try:
            asyncio.run(_run_healthcheck())
        except Exception as exc:
            logger.error(
                "outbound_worker_healthcheck_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise SystemExit(1) from exc
        return
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
