import asyncio
import math
import time
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.ports import RateLimitBackendError, RateLimitDecision

_ATOMIC_FIXED_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
local ttl
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
else
  ttl = redis.call('PTTL', KEYS[1])
  if ttl < 0 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
  end
end
return {current, ttl}
"""


class RedisEvalClient(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...

    async def ping(self) -> object: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class InMemoryFixedWindowRateLimiter:
    """Development-only limiter; state is neither distributed nor durable."""

    def __init__(self, *, requests: int, window_seconds: int) -> None:
        self._requests = requests
        self._window_seconds = window_seconds
        self._windows: dict[str, _Window] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> RateLimitDecision:
        now = time.monotonic()
        async with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self._window_seconds:
                window = _Window(started_at=now, count=0)
                self._windows[key] = window

            window.count += 1
            elapsed = now - window.started_at
            retry_after = max(1, math.ceil(self._window_seconds - elapsed))
            allowed = window.count <= self._requests
            return RateLimitDecision(
                allowed=allowed,
                remaining=max(0, self._requests - window.count),
                retry_after_seconds=retry_after,
            )

    async def ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class RedisFixedWindowRateLimiter:
    """Atomic fixed-window limiter backed by a shared async Redis pool."""

    def __init__(
        self,
        *,
        client: RedisEvalClient,
        requests: int,
        window_seconds: int,
        key_prefix: str = "saltacode:bff:rate:v1",
    ) -> None:
        self._client = client
        self._requests = requests
        self._window_milliseconds = window_seconds * 1_000
        self._key_prefix = key_prefix

    @classmethod
    def from_url(
        cls,
        *,
        url: str,
        requests: int,
        window_seconds: int,
        connect_timeout_seconds: float,
        response_timeout_seconds: float,
    ) -> "RedisFixedWindowRateLimiter":
        client = Redis.from_url(
            url,
            decode_responses=False,
            max_connections=50,
            socket_connect_timeout=connect_timeout_seconds,
            socket_timeout=response_timeout_seconds,
            health_check_interval=30,
        )
        return cls(
            client=client,
            requests=requests,
            window_seconds=window_seconds,
        )

    async def check(self, key: str) -> RateLimitDecision:
        redis_key = f"{self._key_prefix}:{key}"
        try:
            result = await self._client.eval(
                _ATOMIC_FIXED_WINDOW_SCRIPT,
                1,
                redis_key,
                self._window_milliseconds,
            )
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                raise ValueError("unexpected Redis rate-limit result")
            count = int(result[0])
            ttl_milliseconds = int(result[1])
            if count < 1 or ttl_milliseconds < 1:
                raise ValueError("invalid Redis rate-limit counters")
        except (RedisError, TypeError, ValueError, IndexError) as error:
            raise RateLimitBackendError from error

        return RateLimitDecision(
            allowed=count <= self._requests,
            remaining=max(0, self._requests - count),
            retry_after_seconds=max(1, math.ceil(ttl_milliseconds / 1_000)),
        )

    async def ready(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
