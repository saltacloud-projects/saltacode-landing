"""Unit coverage for deterministic commercial handoff coordination."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.contact import Contact, ContactPoint
from app.models.platform import ChatConversation
from app.services.commercial.handoffs import (
    CommercialHandoffConsentRequiredError,
    CommercialHandoffContactEvidenceError,
    CommercialHandoffCoordinator,
    CommercialHandoffRouteRequiredError,
)
from app.services.commercial.opportunities import OpportunityIdempotencyConflictError


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Session:
    def __init__(
        self,
        *,
        route,
        records: dict[tuple[type, object], object],
        execute_values: list[object] | None = None,
    ) -> None:
        self.records = records
        values = iter(execute_values or [None, route])

        async def execute(_statement):
            return _ScalarResult(next(values))

        self.execute = AsyncMock(side_effect=execute)

    async def get(self, model, record_id):
        return self.records.get((model, record_id))


@pytest.mark.asyncio
async def test_quote_handoff_uses_route_and_point_specific_consent() -> None:
    source_agent_id = uuid4()
    target_agent_id = uuid4()
    principal_id = uuid4()
    conversation_id = uuid4()
    contact_id = uuid4()
    point_id = uuid4()
    route = SimpleNamespace(id=uuid4(), target_agent_id=target_agent_id)
    conversation = SimpleNamespace(
        id=conversation_id,
        agent_id=source_agent_id,
        principal_id=principal_id,
    )
    contact = SimpleNamespace(id=contact_id, principal_id=principal_id)
    point = SimpleNamespace(
        id=point_id,
        contact_id=contact_id,
        verification_status="unverified",
    )
    consent = SimpleNamespace(id=uuid4(), contact_id=contact_id)
    opportunity = SimpleNamespace(id=uuid4(), assigned_agent_id=target_agent_id)
    consents = SimpleNamespace(
        effective=AsyncMock(return_value=SimpleNamespace(granted=True, record=consent))
    )
    opportunities = SimpleNamespace(
        create=AsyncMock(
            return_value=SimpleNamespace(opportunity=opportunity, created=True)
        )
    )
    session = _Session(
        route=route,
        records={
            (ChatConversation, conversation_id): conversation,
            (Contact, contact_id): contact,
            (ContactPoint, point_id): point,
        },
    )
    coordinator = CommercialHandoffCoordinator(
        consents=consents,
        opportunities=opportunities,
    )

    result = await coordinator.quote_requested(
        session,
        source_agent_id=source_agent_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        contact_point_id=point_id,
        title="Custom platform",
        summary="The lead requested a quote.",
        correlation_id="handoff-correlation-1",
        idempotency_key="handoff-idempotency-1",
        at=datetime(2026, 9, 6, tzinfo=UTC),
    )

    assert result.created is True
    consents.effective.assert_awaited_once_with(
        session,
        agent_id=source_agent_id,
        principal_id=principal_id,
        purpose="quote_delivery",
        contact_point_id=point_id,
        at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    opportunities.create.assert_awaited_once_with(
        session,
        contact_id=contact_id,
        source_conversation_id=conversation_id,
        created_by_agent_id=source_agent_id,
        assigned_agent_id=target_agent_id,
        assigned_operator_id=None,
        title="Custom platform",
        summary="The lead requested a quote.",
        correlation_id="handoff-correlation-1",
        idempotency_key="handoff-idempotency-1",
    )


@pytest.mark.asyncio
async def test_quote_handoff_requires_an_active_route() -> None:
    coordinator = CommercialHandoffCoordinator()
    session = _Session(route=None, records={})

    with pytest.raises(CommercialHandoffRouteRequiredError):
        await coordinator.quote_requested(
            session,
            source_agent_id=uuid4(),
            conversation_id=uuid4(),
            contact_id=uuid4(),
            contact_point_id=uuid4(),
            title="Quote",
            summary=None,
            correlation_id="route-required",
            idempotency_key="route-required",
        )


@pytest.mark.asyncio
async def test_quote_handoff_rejects_inconsistent_contact_evidence() -> None:
    source_agent_id = uuid4()
    conversation_id = uuid4()
    contact_id = uuid4()
    point_id = uuid4()
    consents = SimpleNamespace(effective=AsyncMock())
    coordinator = CommercialHandoffCoordinator(consents=consents)
    session = _Session(
        route=SimpleNamespace(id=uuid4(), target_agent_id=uuid4()),
        records={
            (
                ChatConversation,
                conversation_id,
            ): SimpleNamespace(
                agent_id=source_agent_id,
                principal_id=uuid4(),
            ),
            (Contact, contact_id): SimpleNamespace(id=contact_id, principal_id=uuid4()),
            (
                ContactPoint,
                point_id,
            ): SimpleNamespace(
                contact_id=contact_id,
                verification_status="unverified",
            ),
        },
    )

    with pytest.raises(CommercialHandoffContactEvidenceError):
        await coordinator.quote_requested(
            session,
            source_agent_id=source_agent_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            contact_point_id=point_id,
            title="Quote",
            summary=None,
            correlation_id="evidence-required",
            idempotency_key="evidence-required",
        )
    consents.effective.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_handoff_requires_current_quote_delivery_consent() -> None:
    source_agent_id = uuid4()
    principal_id = uuid4()
    conversation_id = uuid4()
    contact_id = uuid4()
    point_id = uuid4()
    consents = SimpleNamespace(
        effective=AsyncMock(return_value=SimpleNamespace(granted=False, record=None))
    )
    opportunities = SimpleNamespace(create=AsyncMock())
    coordinator = CommercialHandoffCoordinator(
        consents=consents,
        opportunities=opportunities,
    )
    session = _Session(
        route=SimpleNamespace(id=uuid4(), target_agent_id=uuid4()),
        records={
            (
                ChatConversation,
                conversation_id,
            ): SimpleNamespace(
                agent_id=source_agent_id,
                principal_id=principal_id,
            ),
            (Contact, contact_id): SimpleNamespace(
                id=contact_id,
                principal_id=principal_id,
            ),
            (
                ContactPoint,
                point_id,
            ): SimpleNamespace(
                contact_id=contact_id,
                verification_status="unverified",
            ),
        },
    )

    with pytest.raises(CommercialHandoffConsentRequiredError):
        await coordinator.quote_requested(
            session,
            source_agent_id=source_agent_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            contact_point_id=point_id,
            title="Quote",
            summary=None,
            correlation_id="consent-required",
            idempotency_key="consent-required",
        )
    opportunities.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_handoff_requires_an_explicit_contact_point() -> None:
    session = _Session(route=None, records={})

    with pytest.raises(CommercialHandoffContactEvidenceError):
        await CommercialHandoffCoordinator().quote_requested(
            session,
            source_agent_id=uuid4(),
            conversation_id=uuid4(),
            contact_id=uuid4(),
            contact_point_id=None,
            title="Quote",
            summary=None,
            correlation_id="point-required",
            idempotency_key="point-required",
        )
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_quote_handoff_retry_does_not_depend_on_current_route_or_consent() -> (
    None
):
    source_agent_id = uuid4()
    conversation_id = uuid4()
    contact_id = uuid4()
    opportunity = SimpleNamespace(
        id=uuid4(),
        created_by_agent_id=source_agent_id,
        contact_id=contact_id,
        title="Custom platform",
        summary=None,
    )
    consents = SimpleNamespace(effective=AsyncMock())
    opportunities = SimpleNamespace(create=AsyncMock())
    coordinator = CommercialHandoffCoordinator(
        consents=consents,
        opportunities=opportunities,
    )
    session = _Session(
        route=None,
        records={},
        execute_values=[opportunity, uuid4()],
    )

    result = await coordinator.quote_requested(
        session,
        source_agent_id=source_agent_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        contact_point_id=None,
        title="Custom platform",
        summary=None,
        correlation_id="retry-correlation",
        idempotency_key="stable-retry",
    )

    assert result.created is False
    assert result.opportunity is opportunity
    consents.effective.assert_not_awaited()
    opportunities.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_handoff_retry_rejects_different_semantics() -> None:
    source_agent_id = uuid4()
    conversation_id = uuid4()
    contact_id = uuid4()
    opportunity = SimpleNamespace(
        id=uuid4(),
        created_by_agent_id=source_agent_id,
        contact_id=contact_id,
        title="Original platform",
        summary=None,
    )
    coordinator = CommercialHandoffCoordinator()
    session = _Session(
        route=None,
        records={},
        execute_values=[opportunity, uuid4()],
    )

    with pytest.raises(OpportunityIdempotencyConflictError):
        await coordinator.quote_requested(
            session,
            source_agent_id=source_agent_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            contact_point_id=None,
            title="Different platform",
            summary=None,
            correlation_id="retry-conflict",
            idempotency_key="stable-retry",
        )
