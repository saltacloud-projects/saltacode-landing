"""Hermetic liveness and dependency-readiness tests."""

import httpx
import pytest
from fastapi import FastAPI, status

from app.routers import health as health_router


class _Connection:
    async def execute(self, _statement):
        return None


class _ConnectionContext:
    def __init__(self, error: Exception | None = None):
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return _Connection()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


class _Engine:
    def __init__(self, error: Exception | None = None):
        self._error = error

    def connect(self):
        return _ConnectionContext(self._error)


class _Redis:
    def __init__(self, error: Exception | None = None):
        self._error = error

    async def ping(self):
        if self._error is not None:
            raise self._error
        return True


def _app(redis: _Redis) -> FastAPI:
    app = FastAPI()
    app.state.redis = redis
    app.include_router(health_router.router)
    return app


async def test_health_is_process_liveness():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(_Redis())),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "ok",
        "service": "agent-platform-api",
    }


@pytest.mark.parametrize(
    ("database_error", "redis_error", "expected_status", "expected_checks"),
    [
        (None, None, status.HTTP_200_OK, {"database": "ok", "redis": "ok"}),
        (
            RuntimeError("database credentials must not leak"),
            None,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"database": "error", "redis": "ok"},
        ),
        (
            None,
            RuntimeError("redis endpoint must not leak"),
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"database": "ok", "redis": "error"},
        ),
    ],
)
async def test_ready_reflects_critical_dependency_state(
    monkeypatch,
    database_error,
    redis_error,
    expected_status,
    expected_checks,
):
    monkeypatch.setattr(health_router, "engine", _Engine(database_error))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(_Redis(redis_error))),
        base_url="http://test",
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == expected_status
    assert response.json() == {
        "status": "ok" if expected_status == status.HTTP_200_OK else "degraded",
        "checks": expected_checks,
    }
