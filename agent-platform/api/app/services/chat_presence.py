"""Bounded Redis typing leases, independent of durable AI execution activity."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import ChatConversation
from app.schemas.chat_presence import InboxPresence, TypingSignal, TypingState

TTL_SECONDS = 8
INSTANCE_RETENTION_SECONDS = 32
MAX_INSTANCES = 8
MAX_SIGNALS_PER_SECOND = 6
REDIS_TIMEOUT_SECONDS = 0.25
MAX_PRESENCE_AGENTS = 64
MAX_PRESENCE_CONVERSATIONS = 512
_INDEX = "chat-presence:v1:active"

# An actor-wide rate bucket cannot be bypassed by rotating client instance IDs.
# Stop tombstones retain sequences briefly so reordered starts cannot revive them.
_PUBLISH = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local rows = redis.call('HGETALL', KEYS[1])
local latest = 0
local count = 0
local previous = nil
for i = 1, #rows, 2 do
    local value = cjson.decode(rows[i + 1])
    if value[2] + tonumber(ARGV[5]) <= now then
        redis.call('HDEL', KEYS[1], rows[i])
    else
        count = count + 1
        if rows[i] == ARGV[1] then previous = value end
        latest = math.max(latest, value[3])
    end
end
if previous and tonumber(ARGV[2]) <= tonumber(previous[1]) then
    return {latest > now and latest or 0, 0}
end
local rate = redis.call('INCR', KEYS[2])
if rate == 1 then redis.call('PEXPIRE', KEYS[2], 1000) end
if rate > tonumber(ARGV[7]) then return {0, 1} end
if not previous and count >= tonumber(ARGV[6]) then return {0, 1} end
local expiry = ARGV[3] == '1' and now + tonumber(ARGV[4]) or 0
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode({ARGV[2], now, expiry}))
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[5]))
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if expiry > 0 then
    redis.call('ZADD', KEYS[3], 'GT', expiry, ARGV[8])
    redis.call('PEXPIRE', KEYS[3], tonumber(ARGV[5]))
end
latest = 0
rows = redis.call('HVALS', KEYS[1])
for _, row in ipairs(rows) do latest = math.max(latest, cjson.decode(row)[3]) end
return {latest > now and latest or 0, 0}
"""

_READ = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local latest = 0
for _, row in ipairs(redis.call('HVALS', KEYS[1])) do
    latest = math.max(latest, cjson.decode(row)[3])
end
return latest > now and latest or 0
"""


# Read at most one aggregate budget, not one budget for every authorized agent.
# An extra candidate signals overflow; no partial result can freeze invalidations.
_READ_INDEXES = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local remaining = tonumber(ARGV[1]) + 1
local result = {}
for _, key in ipairs(KEYS) do
    local rows = redis.call('ZRANGEBYSCORE', key, '(' .. now, '+inf', 'LIMIT', 0, remaining)
    for _, row in ipairs(rows) do table.insert(result, row) end
    remaining = remaining - #rows
    if remaining == 0 then return {'overflow'} end
end
return result
"""


@dataclass(frozen=True)
class PresenceRevision:
    metadata: list = field(default_factory=list)
    degraded: bool = False


def _index_key(agent_id: UUID) -> str:
    return f"{_INDEX}:{agent_id}"


class PresenceConflictError(Exception):
    """The signal does not belong to the current human control owner/epoch."""


class PresenceClosedError(Exception):
    """Closed or non-web conversations cannot publish web typing presence."""


class PresenceRateLimitError(Exception):
    """The bounded actor signal budget or active instance limit was exceeded."""


@dataclass(frozen=True)
class PresenceScope:
    conversation_id: UUID
    agent_id: UUID
    channel: str
    control_mode: str
    control_version: int
    automation_version: int
    automation_agent_id: UUID
    status: str
    assigned_admin_id: UUID | None

    @classmethod
    def from_model(cls, conversation: ChatConversation) -> "PresenceScope":
        return cls(
            conversation.id,
            conversation.agent_id,
            conversation.channel,
            conversation.control_mode,
            conversation.control_version,
            conversation.automation_version,
            conversation.automation_agent_id,
            conversation.status,
            conversation.assigned_admin_id,
        )

    @classmethod
    def from_inbox(cls, conversation) -> "PresenceScope":
        return cls(
            conversation.id,
            conversation.routing_agent.id,
            conversation.channel,
            conversation.control_mode,
            conversation.control_version,
            conversation.automation_version,
            conversation.automation_agent.id,
            conversation.status,
            conversation.assigned_operator.id
            if conversation.assigned_operator
            else None,
        )

    @property
    def open(self) -> bool:
        return (
            self.channel == "web"
            and self.status == "active"
            and self.control_mode != "closed"
        )

    def key(self, actor: Literal["visitor", "operator"]) -> str:
        owner = self.assigned_admin_id if actor == "operator" else "visitor"
        return (
            f"chat-presence:v1:{self.agent_id}:{self.conversation_id}:"
            f"{self.control_version}:{self.automation_version}:"
            f"{self.automation_agent_id}:{actor}:{owner}"
        )

    def actor_allowed(self, actor: str) -> bool:
        return self.open and (
            actor == "visitor"
            or (self.control_mode == "human" and self.assigned_admin_id is not None)
        )


def _state(expiry: int) -> TypingState:
    if not expiry:
        return TypingState()
    return TypingState(
        typing=True, expires_at=datetime.fromtimestamp(int(expiry) / 1000, UTC)
    )


async def publish_presence(
    redis,
    *,
    scope: PresenceScope,
    signal: TypingSignal,
    actor: Literal["visitor", "operator"],
    actor_admin_id: UUID | None = None,
    expected_control_version: int | None = None,
) -> TypingState:
    if not scope.open:
        raise PresenceClosedError("Conversation does not accept typing presence")
    if actor == "operator" and (
        not scope.actor_allowed(actor)
        or scope.assigned_admin_id != actor_admin_id
        or scope.control_version != expected_control_version
    ):
        raise PresenceConflictError("Current human control is required")
    if redis is None:
        return TypingState()
    owner = actor_admin_id if actor == "operator" else "visitor"
    rate_key = f"chat-presence:v1:rate:{scope.conversation_id}:{actor}:{owner}"
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            expiry, limited = await redis.eval(
                _PUBLISH,
                3,
                scope.key(actor),
                rate_key,
                _index_key(scope.agent_id),
                str(signal.client_instance_id),
                signal.sequence,
                int(signal.typing),
                TTL_SECONDS * 1000,
                INSTANCE_RETENTION_SECONDS * 1000,
                MAX_INSTANCES,
                MAX_SIGNALS_PER_SECOND,
                str(scope.conversation_id),
            )
            if limited:
                raise PresenceRateLimitError("Typing signal limit exceeded")
            return _state(expiry)
    except (RedisError, TimeoutError, ValueError, TypeError):
        return TypingState()


async def read_presence(
    redis, scopes: list[PresenceScope]
) -> dict[UUID, InboxPresence]:
    results = {scope.conversation_id: InboxPresence() for scope in scopes}
    if redis is None or not scopes or len(scopes) > MAX_PRESENCE_CONVERSATIONS:
        return results
    requests = [
        (scope, actor)
        for scope in scopes
        for actor in ("visitor", "operator")
        if scope.actor_allowed(actor)
    ]
    if not requests:
        return results
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            async with redis.pipeline(transaction=False) as pipeline:
                for scope, actor in requests:
                    pipeline.eval(_READ, 1, scope.key(actor))
                values = await pipeline.execute()
            for (scope, actor), expiry in zip(requests, values, strict=True):
                setattr(results[scope.conversation_id], actor, _state(expiry))
    except (RedisError, TimeoutError, ValueError, TypeError):
        return {scope.conversation_id: InboxPresence() for scope in scopes}
    return results


async def enrich_presence(redis, conversations) -> None:
    states = await read_presence(
        redis,
        [PresenceScope.from_inbox(conversation) for conversation in conversations],
    )
    for conversation in conversations:
        conversation.presence = states[conversation.id]


async def presence_revision(
    db: AsyncSession, redis, agent_ids: tuple[UUID, ...]
) -> PresenceRevision:
    """Bound presence work independently of total CRM history and agent count."""
    if redis is None or not agent_ids:
        return PresenceRevision()
    if len(agent_ids) > MAX_PRESENCE_AGENTS:
        return PresenceRevision(["capacity"], degraded=True)
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            values = await redis.eval(
                _READ_INDEXES,
                len(agent_ids),
                *(_index_key(agent_id) for agent_id in agent_ids),
                MAX_PRESENCE_CONVERSATIONS,
            )
            candidates = [
                value.decode() if isinstance(value, bytes) else value
                for value in values
            ]
            if candidates == ["overflow"]:
                return PresenceRevision(["capacity"], degraded=True)
            ids = tuple({UUID(value) for value in candidates})
    except (RedisError, TimeoutError, ValueError, TypeError):
        return PresenceRevision(["unavailable"], degraded=True)
    if not ids:
        return PresenceRevision()
    conversations = (
        await db.scalars(
            select(ChatConversation).where(
                ChatConversation.id.in_(ids), ChatConversation.agent_id.in_(agent_ids)
            )
        )
    ).all()
    states = await read_presence(
        redis,
        [PresenceScope.from_model(conversation) for conversation in conversations],
    )
    return PresenceRevision(
        sorted(
            (str(identifier), state.model_dump_json())
            for identifier, state in states.items()
            if state.visitor.typing or state.operator.typing
        )
    )
