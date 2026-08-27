"""
Tests de `app.core.dedup_lock` — idempotencia y lock por phone_number.

Cubre:
  - claim_message_id: nuevo, duplicado, Redis caído, message_id vacío
  - conversation_lock: adquisición exitosa, contención simultánea, Redis caído

No requiere PostgreSQL ni servicios externos — mockea Redis con un fake en memoria.

Ejecutar:
    docker compose exec api pytest tests/test_dedup_lock.py -v
"""

import asyncio
import os

import pytest

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("SIM_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")
os.environ.setdefault("FASTAPI_API_KEY", "test-key")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test")

from app.core.dedup_lock import (
    DEDUP_TTL_SECONDS,
    LOCK_TTL_SECONDS,
    claim_message_id,
    conversation_lock,
)

# ═════════════════════════════════════════════════════════════════════════════
# Fake Redis mínimo
# ═════════════════════════════════════════════════════════════════════════════


class FakeRedis:
    """Implementa la API mínima de redis.asyncio que usamos en dedup_lock."""

    def __init__(self):
        self._store: dict[str, tuple[str, float | None]] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ):
        loop_time = asyncio.get_event_loop().time()
        # Evict expired keys (simplified — we ignore TTLs in tests for simplicity)
        if nx and key in self._store:
            existing, expires_at = self._store[key]
            if expires_at is None or expires_at > loop_time:
                return None  # NX falla
        expires_at = loop_time + ex if ex else None
        self._store[key] = (value, expires_at)
        return True

    async def get(self, key: str) -> str | None:
        loop_time = asyncio.get_event_loop().time()
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if expires_at is not None and expires_at <= loop_time:
            del self._store[key]
            return None
        return value

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def eval(self, script: str, num_keys: int, *args):
        # Solo implementamos el patrón "delete if equal" usado por el release.
        key = args[0]
        expected = args[1]
        current = await self.get(key)
        if current == expected:
            await self.delete(key)
            return 1
        return 0


class BrokenRedis:
    """Falla en cada operación — simula Redis caído para verificar fail-open."""

    async def set(self, *args, **kwargs):
        raise RuntimeError("redis down")

    async def get(self, *args, **kwargs):
        raise RuntimeError("redis down")

    async def delete(self, *args, **kwargs):
        raise RuntimeError("redis down")

    async def eval(self, *args, **kwargs):
        raise RuntimeError("redis down")


# ═════════════════════════════════════════════════════════════════════════════
# claim_message_id
# ═════════════════════════════════════════════════════════════════════════════


class TestClaimMessageId:
    @pytest.mark.asyncio
    async def test_new_message_id_returns_true(self):
        redis = FakeRedis()
        ok = await claim_message_id(redis, "wamid.123")
        assert ok is True

    @pytest.mark.asyncio
    async def test_duplicate_returns_false(self):
        redis = FakeRedis()
        first = await claim_message_id(redis, "wamid.dup")
        second = await claim_message_id(redis, "wamid.dup")
        assert first is True
        assert second is False

    @pytest.mark.asyncio
    async def test_empty_message_id_returns_true(self):
        """Si el message_id viene vacío, no podemos deduplicar — fail-open."""
        redis = FakeRedis()
        assert await claim_message_id(redis, None) is True
        assert await claim_message_id(redis, "") is True

    @pytest.mark.asyncio
    async def test_redis_none_returns_true(self):
        """Sin Redis, no hay dedupe — fail-open al pipeline."""
        assert await claim_message_id(None, "wamid.xyz") is True

    @pytest.mark.asyncio
    async def test_redis_broken_returns_true(self):
        """Si Redis falla, no debemos bloquear al usuario — fail-open."""
        redis = BrokenRedis()
        ok = await claim_message_id(redis, "wamid.abc")
        assert ok is True

    @pytest.mark.asyncio
    async def test_dedup_ttl_is_long(self):
        """El TTL debe ser de al menos varios días para cubrir reinicios y reintentos de Meta."""
        assert DEDUP_TTL_SECONDS >= 24 * 3600


# ═════════════════════════════════════════════════════════════════════════════
# conversation_lock
# ═════════════════════════════════════════════════════════════════════════════


class TestConversationLock:
    @pytest.mark.asyncio
    async def test_acquires_lock_when_free(self):
        redis = FakeRedis()
        async with conversation_lock(redis, "5491111", "req-1") as acquired:
            assert acquired is True
        # tras liberar, debe poder readquirirse
        async with conversation_lock(redis, "5491111", "req-2") as acquired_again:
            assert acquired_again is True

    @pytest.mark.asyncio
    async def test_serializes_same_phone(self):
        """Dos tareas concurrentes para el mismo phone deben ejecutarse en orden."""
        redis = FakeRedis()
        order: list[str] = []

        async def worker(name: str):
            async with conversation_lock(
                redis, "5492222", f"req-{name}", timeout_seconds=3
            ) as acq:
                # Aunque entremos sin lock, debemos registrar el inicio
                order.append(f"start-{name}")
                await asyncio.sleep(0.05)
                order.append(f"end-{name}")
                return acq

        results = await asyncio.gather(worker("A"), worker("B"))

        # Ambos deben terminar (segundo puede haber esperado al primero)
        assert all(r in (True, False) for r in results)
        # Las ejecuciones no deben entrelazarse cuando ambos consiguen el lock
        # (start-A → end-A → start-B → end-B  ó  start-B → end-B → start-A → end-A)
        assert order in (
            ["start-A", "end-A", "start-B", "end-B"],
            ["start-B", "end-B", "start-A", "end-A"],
        ), f"Orden inesperado, pueden estar interleaved: {order}"

    @pytest.mark.asyncio
    async def test_different_phones_dont_block(self):
        """Locks de phones distintos NO deben bloquearse entre sí."""
        redis = FakeRedis()
        order: list[str] = []

        async def worker(phone: str, label: str):
            async with conversation_lock(redis, phone, f"req-{label}") as acq:
                order.append(f"start-{label}")
                await asyncio.sleep(0.05)
                order.append(f"end-{label}")
                return acq

        await asyncio.gather(worker("549A", "A"), worker("549B", "B"))

        # Deberían entrelazarse (start-A, start-B antes de end-A, end-B)
        assert order.index("start-A") < order.index("end-B")
        assert order.index("start-B") < order.index("end-A")

    @pytest.mark.asyncio
    async def test_redis_none_yields_false(self):
        """Sin Redis, el lock degrada a fail-open (yield False)."""
        async with conversation_lock(None, "549XXXX", "req-no-redis") as acquired:
            assert acquired is False

    @pytest.mark.asyncio
    async def test_redis_broken_yields_false(self):
        """Si Redis falla durante SET, degradar a fail-open."""
        redis = BrokenRedis()
        async with conversation_lock(redis, "549YYYY", "req-broken") as acquired:
            assert acquired is False

    @pytest.mark.asyncio
    async def test_lock_ttl_is_reasonable(self):
        """El TTL del lock debe cubrir un pipeline lento pero no ser tan largo que cuelgue por horas."""
        assert 30 <= LOCK_TTL_SECONDS <= 600
