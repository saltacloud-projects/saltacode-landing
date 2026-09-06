"""Configuration and loop behavior for durable follow-up execution."""

import asyncio
from datetime import UTC, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.commercial.follow_up_execution import (
    _compose_message,
    _quiet_hours_end,
)
from app.workers.follow_ups import FollowUpWorker


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("follow_up_worker_poll_seconds", 0),
        ("follow_up_worker_max_backoff_seconds", 0.5),
        ("follow_up_worker_max_backoff_seconds", 301),
        ("follow_up_execution_lease_seconds", 29),
        ("follow_up_execution_lease_seconds", 3_601),
    ],
)
def test_follow_up_worker_settings_reject_unsafe_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(
            postgres_dsn="postgresql+asyncpg://test:test@localhost/test",
            fastapi_api_key="test",
            **{field: value},
        )


@pytest.mark.asyncio
async def test_worker_backs_off_and_shuts_down_cooperatively(monkeypatch):
    from app.workers import follow_ups as module

    stop_event = asyncio.Event()
    runner = AsyncMock()
    runner.run_once.side_effect = RuntimeError("synthetic failure")
    worker = FollowUpWorker(
        runner,
        poll_seconds=0.1,
        max_backoff_seconds=1.0,
    )

    async def stop_after_wait(event, delay):
        assert delay == 0.2
        event.set()

    monkeypatch.setattr(worker, "_wait_or_stop", stop_after_wait)
    dispose = AsyncMock()
    monkeypatch.setattr(module, "engine", SimpleNamespace(dispose=dispose))

    await worker.run_forever(stop_event)

    runner.run_once.assert_awaited_once()
    dispose.assert_awaited_once()


def test_quiet_hours_support_overnight_agent_timezone():
    policy = SimpleNamespace(
        quiet_hours_start=time(22),
        quiet_hours_end=time(8),
        timezone="America/Argentina/Salta",
    )

    deferred_until = _quiet_hours_end(
        policy=policy,
        now=datetime(2026, 9, 6, 6, tzinfo=UTC),
    )

    assert deferred_until == datetime(2026, 9, 6, 11, tzinfo=UTC)


def test_composer_is_deterministic_and_does_not_interpolate_private_input():
    messages = {
        _compose_message("commercial_follow_up"),
        _compose_message("meeting_coordination"),
        _compose_message("proposal_reminder"),
    }

    assert len(messages) == 3
    assert all("secret@example.invalid" not in message for message in messages)
