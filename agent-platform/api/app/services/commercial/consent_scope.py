"""Canonical target-scoped consent serialization primitives."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_SCOPE_VERSION = "commercial-consent-scope-v1"


@dataclass(frozen=True, slots=True)
class ConsentScope:
    """Immutable authorization scope shared by consent and queued work."""

    routing_agent_id: uuid.UUID
    principal_id: uuid.UUID
    purpose: StrEnum | str
    source_conversation_id: uuid.UUID
    target_channel: str
    contact_point_id: uuid.UUID

    def canonical(self) -> str:
        purpose = (
            self.purpose.value if isinstance(self.purpose, StrEnum) else self.purpose
        )
        return ":".join(
            (
                _SCOPE_VERSION,
                str(self.routing_agent_id),
                str(self.principal_id),
                purpose,
                str(self.source_conversation_id),
                self.target_channel,
                str(self.contact_point_id),
            )
        )

    def advisory_key(self) -> int:
        return int.from_bytes(
            hashlib.sha256(self.canonical().encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )


async def acquire_consent_scope_lock(
    db: AsyncSession,
    *,
    scope: ConsentScope,
) -> None:
    """Serialize grant, revoke, scheduling, requeue, and future dispatch."""

    await db.execute(select(func.pg_advisory_xact_lock(scope.advisory_key())))
