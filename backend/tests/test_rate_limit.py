import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.config import Settings
from app.main import create_app
from app.ports import RateLimitBackendError, RateLimitDecision
from app.rate_limit import RedisFixedWindowRateLimiter


class AtomicFakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.lock = asyncio.Lock()
        self.closed = False

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        assert "INCR" in script and "PEXPIRE" in script
        assert numkeys == 1
        key = str(keys_and_args[0])
        window_milliseconds = int(keys_and_args[1])
        async with self.lock:
            await asyncio.sleep(0)
            count = self.counts.get(key, 0) + 1
            self.counts[key] = count
            return [count, window_milliseconds]

    async def ping(self) -> object:
        return True

    async def aclose(self) -> None:
        self.closed = True


class UnavailableFakeRedis(AtomicFakeRedis):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        raise ConnectionError("Redis unavailable")

    async def ping(self) -> object:
        raise ConnectionError("Redis unavailable")


class UnavailableRateLimiter:
    async def check(self, key: str) -> RateLimitDecision:
        raise RateLimitBackendError

    async def ready(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_fixed_window_is_atomic_under_concurrency() -> None:
    client = AtomicFakeRedis()
    limiter = RedisFixedWindowRateLimiter(
        client=client,
        requests=10,
        window_seconds=60,
    )

    decisions = await asyncio.gather(*(limiter.check("same-client") for _ in range(100)))

    assert sum(decision.allowed for decision in decisions) == 10
    assert sum(not decision.allowed for decision in decisions) == 90
    assert client.counts["saltacode:bff:rate:v1:same-client"] == 100
    assert all(decision.retry_after_seconds == 60 for decision in decisions)
    await limiter.aclose()
    assert client.closed is True


@pytest.mark.asyncio
async def test_redis_outage_fails_closed() -> None:
    limiter = RedisFixedWindowRateLimiter(
        client=UnavailableFakeRedis(),
        requests=10,
        window_seconds=60,
    )

    with pytest.raises(RateLimitBackendError):
        await limiter.check("same-client")
    assert await limiter.ready() is False


def test_redis_outage_returns_safe_http_failures() -> None:
    settings = Settings(app_env="test")
    message = "private-message-that-must-not-be-echoed"
    request = {
        "client_message_id": str(uuid4()),
        "message": message,
        "locale": "es-AR",
        "transcript_consent": True,
        "privacy_version": "privacy-v1",
    }

    with TestClient(create_app(settings, rate_limiter=UnavailableRateLimiter())) as client:
        ready = client.get("/health/ready")
        response = client.post("/api/v1/chat", json=request)

    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "rate_limit_unavailable"
    assert message not in response.text
