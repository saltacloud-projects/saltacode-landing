"""Enforce each agent profile's conversation retention policy."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.platform import ChatConversation

logger = logging.getLogger(__name__)


async def purge_expired_conversations(
    db: AsyncSession, *, now: datetime | None = None
) -> int:
    """Delete expired conversations; database cascades remove messages/executions."""

    reference = now or datetime.now(timezone.utc)
    policies = (
        await db.execute(
            select(AgentProfile.id, AgentProfile.retention_days).where(
                AgentProfile.retention_days > 0
            )
        )
    ).all()

    deleted_count = 0
    for agent_id, retention_days in policies:
        cutoff = reference - timedelta(days=retention_days)
        deleted = await db.execute(
            delete(ChatConversation)
            .where(
                ChatConversation.agent_id == agent_id,
                ChatConversation.updated_at < cutoff,
            )
            .returning(ChatConversation.id)
        )
        deleted_count += len(deleted.scalars().all())

    await db.commit()
    return deleted_count


async def run_retention_sweeper(
    session_factory: Callable[[], AsyncSession], interval_seconds: int
) -> None:
    """Periodically enforce retention without coupling policy to transports."""

    interval = max(interval_seconds, 60)
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_factory() as db:
                deleted_count = await purge_expired_conversations(db)
            if deleted_count:
                logger.info(
                    "expired_conversations_deleted",
                    extra={"count": deleted_count},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("conversation_retention_sweep_failed")
