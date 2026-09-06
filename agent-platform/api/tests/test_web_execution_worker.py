"""Unit contracts for the cooperative durable web execution worker."""

import asyncio

import pytest

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


def test_worker_rejects_invalid_poll_and_backoff_timing():
    with pytest.raises(ValueError):
        WebExecutionWorker(_Runner([]), poll_seconds=0, max_backoff_seconds=1)
    with pytest.raises(ValueError):
        WebExecutionWorker(_Runner([]), poll_seconds=2, max_backoff_seconds=1)


@pytest.mark.asyncio
async def test_worker_continues_immediately_after_work_and_backs_off_on_failure(
    monkeypatch,
):
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

    await worker.run_forever(stop_event)

    assert runner.calls == 3
    assert delays == [0.2, 0.1]
