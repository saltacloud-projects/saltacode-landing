"""Entrypoint for the durable external-channel ingress worker."""

import asyncio
import logging
import sys

from sqlalchemy import text

from app.core.database import engine
from app.core.logging import setup_logging
from app.services.channel_inbound import channel_inbound_worker

logger = logging.getLogger(__name__)
_REQUIRED_COLUMNS = {
    "id",
    "channel",
    "adapter_key",
    "adapter_version",
    "channel_route_id",
    "channel_route_version",
    "route_key_snapshot",
    "channel_connection_id",
    "channel_connection_version",
    "routing_agent_id",
    "provider_message_id",
    "thread_key",
    "payload_ciphertext",
    "payload_hash",
    "legacy_payload_json",
    "status",
    "phase",
    "state_version",
    "attempts",
    "lease_owner",
    "lease_expires_at",
    "safe_code",
    "created_at",
    "updated_at",
}


async def check_worker_health() -> None:
    """Verify database reachability, Alembic state and neutral inbox schema."""
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
                        "AND table_name = 'channel_inbound_jobs'"
                    )
                )
            )
            .scalars()
            .all()
        )
        if not _REQUIRED_COLUMNS.issubset(columns):
            raise RuntimeError("Channel inbound migration is unavailable")
        await connection.execute(text("SELECT 1 FROM channel_inbound_jobs LIMIT 0"))


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
                "channel_inbound_healthcheck_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise SystemExit(1) from exc
        return
    asyncio.run(channel_inbound_worker.run_forever())


if __name__ == "__main__":
    main()
