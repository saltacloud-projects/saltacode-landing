"""Semantic command boundary tests for follow-up operations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.commercial.follow_ups import FollowUpService, FollowUpStatus


@pytest.mark.asyncio
async def test_requeue_requires_review_source_and_full_delivery_readiness() -> None:
    service = FollowUpService()
    transition = AsyncMock(return_value=SimpleNamespace(status="scheduled"))
    service.transition = transition

    await service.requeue(
        SimpleNamespace(),
        task_id=uuid4(),
        actor_agent_id=uuid4(),
        actor_operator_id=uuid4(),
        expected_version=2,
        correlation_id="requeue-test",
        idempotency_key="requeue-test",
    )

    assert transition.await_args.kwargs["target_status"] is FollowUpStatus.SCHEDULED
    assert transition.await_args.kwargs["allowed_source_statuses"] == frozenset(
        {FollowUpStatus.REVIEW_REQUIRED}
    )
    assert transition.await_args.kwargs["require_delivery_readiness"] is True


@pytest.mark.asyncio
async def test_cancel_cannot_operate_after_delivery_has_started() -> None:
    service = FollowUpService()
    transition = AsyncMock(return_value=SimpleNamespace(status="cancelled"))
    service.transition = transition

    await service.cancel(
        SimpleNamespace(),
        task_id=uuid4(),
        actor_agent_id=uuid4(),
        actor_operator_id=uuid4(),
        expected_version=1,
        correlation_id="cancel-test",
        idempotency_key="cancel-test",
    )

    assert transition.await_args.kwargs["allowed_source_statuses"] == frozenset(
        {FollowUpStatus.SCHEDULED, FollowUpStatus.REVIEW_REQUIRED}
    )


@pytest.mark.asyncio
async def test_cancel_review_resolution_only_operates_on_review_work() -> None:
    service = FollowUpService()
    transition = AsyncMock(return_value=SimpleNamespace(status="cancelled"))
    service.transition = transition

    await service.resolve_review(
        SimpleNamespace(),
        task_id=uuid4(),
        actor_agent_id=uuid4(),
        actor_operator_id=uuid4(),
        expected_version=3,
        resolution="cancel",
        correlation_id="review-cancel-test",
        idempotency_key="review-cancel-test",
    )

    assert transition.await_args.kwargs["target_status"] is FollowUpStatus.CANCELLED
    assert transition.await_args.kwargs["allowed_source_statuses"] == frozenset(
        {FollowUpStatus.REVIEW_REQUIRED}
    )
