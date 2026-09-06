"""Configuration and Compose contracts for the outbound worker."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.workers.outbound import OutboundWorker


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outbound_worker_poll_seconds", 0),
        ("outbound_worker_max_backoff_seconds", 0.5),
        ("outbound_worker_max_backoff_seconds", 301),
        ("outbound_dispatch_stale_seconds", 59),
    ],
)
def test_outbound_worker_settings_reject_unsafe_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(
            postgres_dsn="postgresql+asyncpg://test:test@localhost/test",
            fastapi_api_key="test",
            **{field: value},
        )


def test_compose_defines_a_separate_inactive_outbound_worker():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    worker = compose[compose.index("  outbound-worker:") :]

    assert 'profiles: ["outbound"]' in worker
    assert 'command: ["python", "-m", "app.workers.outbound"]' in worker
    assert '"app.workers.outbound"' in worker
    assert '"--healthcheck"' in worker
    assert "OUTBOUND_DISPATCH_STALE_SECONDS:-300" in compose


@pytest.mark.asyncio
async def test_worker_backs_off_and_shuts_down_cooperatively(monkeypatch):
    from app.workers import outbound as module

    stop_event = asyncio.Event()
    dispatcher = AsyncMock()
    dispatcher.run_once.side_effect = RuntimeError("synthetic failure")
    worker = OutboundWorker(dispatcher)

    async def stop_after_wait(event, delay):
        assert delay == 0.2
        event.set()

    monkeypatch.setattr(module.settings, "outbound_worker_poll_seconds", 0.1)
    monkeypatch.setattr(module.settings, "outbound_worker_max_backoff_seconds", 1.0)
    monkeypatch.setattr(worker, "_wait_or_stop", stop_after_wait)
    dispose = AsyncMock()
    monkeypatch.setattr(module, "engine", SimpleNamespace(dispose=dispose))

    await worker.run_forever(stop_event)

    dispatcher.run_once.assert_awaited_once()
    dispose.assert_awaited_once()
