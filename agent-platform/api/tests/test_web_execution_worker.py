"""Unit contracts for the cooperative durable web execution worker."""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.workers.web_executions import WebExecutionWorker


class _Runner:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def run_once(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _compose_service(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match.group("body")


def test_worker_rejects_invalid_poll_and_backoff_timing():
    with pytest.raises(ValueError):
        WebExecutionWorker(_Runner([]), poll_seconds=0, max_backoff_seconds=1)
    with pytest.raises(ValueError):
        WebExecutionWorker(_Runner([]), poll_seconds=2, max_backoff_seconds=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("web_execution_worker_poll_seconds", 0),
        ("web_execution_worker_max_backoff_seconds", 0.5),
        ("web_execution_worker_max_backoff_seconds", 301),
        ("web_execution_lease_seconds", 900),
        ("web_execution_lease_seconds", 86_401),
    ],
)
def test_web_execution_worker_settings_reject_unsafe_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(
            postgres_dsn="postgresql+asyncpg://test:test@localhost/test",
            fastapi_api_key="test",
            **{field: value},
        )


def test_compose_requires_single_web_execution_worker_with_schema_healthcheck():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    worker = _compose_service(compose, "web-execution-worker")

    assert "profiles:" not in worker
    assert 'command: ["python", "-m", "app.workers.web_executions"]' in worker
    assert '"app.workers.web_executions"' in worker
    assert '"--healthcheck"' in worker
    assert "replicas: 1" in worker
    assert "WEB_EXECUTION_LEASE_SECONDS:-1200" in compose


def test_compose_limits_egress_network_to_provider_callers():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    for service in (
        "api",
        "rag-worker",
        "whatsapp-worker",
        "outbound-worker",
        "web-execution-worker",
    ):
        assert "egress" in _compose_service(compose, service)
    for service in (
        "postgres",
        "redis",
        "migrate",
        "bootstrap",
        "integration-tests",
        "panel",
    ):
        assert "egress" not in _compose_service(compose, service)


@pytest.mark.asyncio
async def test_worker_continues_immediately_after_work_and_backs_off_on_failure(
    monkeypatch,
):
    from app.workers import web_executions as module

    runner = _Runner([True, RuntimeError("transient"), False])
    worker = WebExecutionWorker(
        runner,
        poll_seconds=0.1,
        max_backoff_seconds=0.4,
    )
    stop_event = asyncio.Event()
    delays = []

    async def wait_or_stop(_stop_event, delay):
        delays.append(delay)
        if len(delays) == 2:
            stop_event.set()

    monkeypatch.setattr(worker, "_wait_or_stop", wait_or_stop)
    dispose = AsyncMock()
    monkeypatch.setattr(module, "engine", SimpleNamespace(dispose=dispose))

    await worker.run_forever(stop_event)

    assert runner.calls == 3
    assert delays == [0.2, 0.1]
    dispose.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_web_execution_worker_healthchecks_durable_schema():
    from app.workers.web_executions import check_worker_health

    await check_worker_health()


@pytest.mark.asyncio
async def test_web_execution_healthcheck_disposes_database_engine(monkeypatch):
    from app.workers import web_executions as module

    healthcheck = AsyncMock()
    dispose = AsyncMock()
    monkeypatch.setattr(module, "check_worker_health", healthcheck)
    monkeypatch.setattr(module, "engine", SimpleNamespace(dispose=dispose))

    await module._run_healthcheck()

    healthcheck.assert_awaited_once()
    dispose.assert_awaited_once()
