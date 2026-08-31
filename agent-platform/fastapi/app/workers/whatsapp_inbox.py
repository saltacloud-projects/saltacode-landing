"""Entrypoint for the durable WhatsApp inbox worker."""

import asyncio
import logging
import sys

from sqlalchemy import text

from app.core.database import engine
from app.core.logging import setup_logging
from app.services.whatsapp_inbox import whatsapp_inbox_worker

logger = logging.getLogger(__name__)
_REQUIRED_INBOX_COLUMNS = {
    "id",
    "channel_route_id",
    "channel_connection_id",
    "provider_message_id",
    "payload_json",
    "status",
    "attempts",
    "max_attempts",
    "locked_by",
    "locked_at",
    "next_attempt_at",
    "error_code",
    "error_message",
    "completed_at",
    "created_at",
    "updated_at",
}


async def check_worker_health() -> None:
    """Verify database reachability, Alembic state and the inbox schema."""
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
                        "AND table_name = 'whatsapp_inbound_jobs'"
                    )
                )
            )
            .scalars()
            .all()
        )
        if not _REQUIRED_INBOX_COLUMNS.issubset(columns):
            raise RuntimeError("WhatsApp inbox migration is unavailable")
        await connection.execute(text("SELECT 1 FROM whatsapp_inbound_jobs LIMIT 0"))


async def _run_healthcheck() -> None:
    try:
        await check_worker_health()
    finally:
        await engine.dispose()


def main() -> None:
    setup_logging()
    if "--healthcheck" in sys.argv[1:]:
        try:
            asyncio.run(_run_healthcheck())
        except Exception as exc:
            logger.error(
                "whatsapp_inbox_healthcheck_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise SystemExit(1) from exc
        return
    asyncio.run(whatsapp_inbox_worker.run_forever())


if __name__ == "__main__":
    main()
