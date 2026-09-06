"""Cooperative polling loop for durable web-chat executions."""

from __future__ import annotations

import asyncio
import logging

from app.services.web_execution_runner import WebExecutionRunner

logger = logging.getLogger(__name__)


class WebExecutionWorker:
    """Poll one configured runner with bounded failure backoff."""

    def __init__(
        self,
        runner: WebExecutionRunner,
        *,
        poll_seconds: float,
        max_backoff_seconds: float,
    ) -> None:
        if poll_seconds <= 0 or max_backoff_seconds < poll_seconds:
            raise ValueError("invalid web execution worker timing")
        self._runner = runner
        self._poll_seconds = poll_seconds
        self._max_backoff_seconds = max_backoff_seconds

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        delay = self._poll_seconds
        logger.info("web_execution_worker_started")
        while not stop_event.is_set():
            try:
                processed = await self._runner.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "web_execution_worker_iteration_failed",
                    extra={"error_type": type(exc).__name__},
                )
                delay = min(self._max_backoff_seconds, max(delay * 2, delay))
            else:
                delay = self._poll_seconds
                if processed:
                    continue
            await self._wait_or_stop(stop_event, delay)
        logger.info("web_execution_worker_stopped")

    @staticmethod
    async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            return
