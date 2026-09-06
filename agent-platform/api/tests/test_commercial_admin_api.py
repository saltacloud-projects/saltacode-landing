"""Administration contract tests for the agent-scoped commercial workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers.admin.commercial import (
    create_quote_request,
    get_opportunity,
    router,
    transition_opportunity_stage,
)
from app.schemas.commercial import (
    OpportunityStageTransitionRequest,
    QuoteRequestCreateRequest,
)
from app.services.commercial.read_models import CommercialReadNotFoundError

ROOT = "/api/admin/agents/{agent_id}/opportunities"


def test_commercial_contract_is_agent_scoped_authenticated_and_non_destructive() -> (
    None
):
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    expected = {
        (f"{ROOT}/", "get"),
        (f"{ROOT}/", "post"),
        (f"{ROOT}/candidates", "get"),
        (f"{ROOT}/operators", "get"),
        (f"{ROOT}/consent-revocations", "post"),
        (f"{ROOT}/automation-policy", "get"),
        (f"{ROOT}/automation-policy", "put"),
        (f"{ROOT}/{{opportunity_id}}", "get"),
        (f"{ROOT}/{{opportunity_id}}/stage-transitions", "post"),
        (f"{ROOT}/{{opportunity_id}}/reassignments", "post"),
        (f"{ROOT}/{{opportunity_id}}/conversation-links", "post"),
        (f"{ROOT}/{{opportunity_id}}/follow-ups", "post"),
        (
            f"{ROOT}/{{opportunity_id}}/follow-ups/{{task_id}}/transitions",
            "post",
        ),
        (f"{ROOT}/{{opportunity_id}}/quote-requests", "post"),
        (
            f"{ROOT}/{{opportunity_id}}/quote-requests/"
            "{quote_request_id}/authoritative-versions",
            "post",
        ),
    }

    for path, method in expected:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"HTTPBearer": []}]
        agent_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "agent_id" and parameter["in"] == "path"
        )
        assert agent_parameter["required"] is True

    assert not any(
        "delete" in methods
        for path, methods in schema["paths"].items()
        if "/opportunities" in path
    )


def test_commercial_commands_expose_idempotency_and_optimistic_versions() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    idempotent_paths = [
        f"{ROOT}/",
        f"{ROOT}/{{opportunity_id}}/stage-transitions",
        f"{ROOT}/{{opportunity_id}}/reassignments",
        f"{ROOT}/{{opportunity_id}}/conversation-links",
        f"{ROOT}/{{opportunity_id}}/follow-ups",
        f"{ROOT}/consent-revocations",
        f"{ROOT}/{{opportunity_id}}/quote-requests",
        f"{ROOT}/{{opportunity_id}}/quote-requests/"
        "{quote_request_id}/authoritative-versions",
    ]
    for path in idempotent_paths:
        operation = schema["paths"][path]["post"]
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["required"] is True

    stage_schema = schema["components"]["schemas"]["OpportunityStageTransitionRequest"][
        "properties"
    ]
    reassign_schema = schema["components"]["schemas"]["OpportunityReassignmentRequest"][
        "properties"
    ]
    follow_up_schema = schema["components"]["schemas"]["FollowUpTransitionRequest"][
        "properties"
    ]
    quote_version_schema = schema["components"]["schemas"][
        "AuthoritativeQuoteVersionCreateRequest"
    ]["properties"]
    automation_policy_schema = schema["components"]["schemas"][
        "CommercialAutomationPolicyUpdateRequest"
    ]["properties"]
    assert all(
        "expected_version" in contract
        for contract in [
            stage_schema,
            reassign_schema,
            follow_up_schema,
            quote_version_schema,
            automation_policy_schema,
        ]
    )


def test_consent_revocation_rejects_unauthenticated_callers() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)

    response = TestClient(app).post(
        f"/api/admin/agents/{uuid4()}/opportunities/consent-revocations",
        headers={"Idempotency-Key": "unauthenticated-revocation"},
        json={
            "source_conversation_id": str(uuid4()),
            "contact_point_id": str(uuid4()),
            "target_channel": "email",
            "policy_version": "commercial-v1",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_out_of_scope_detail_returns_the_same_non_enumerable_404(
    monkeypatch,
) -> None:
    read = AsyncMock(side_effect=CommercialReadNotFoundError("different agent"))
    monkeypatch.setattr(
        "app.routers.admin.commercial.commercial_read_service.get_opportunity",
        read,
    )

    with pytest.raises(HTTPException) as error:
        await get_opportunity(
            agent_id=uuid4(),
            opportunity_id=uuid4(),
            db=SimpleNamespace(),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Commercial resource not found"


@pytest.mark.asyncio
async def test_stage_transition_checks_current_route_ownership_before_mutation(
    monkeypatch,
) -> None:
    agent_id = uuid4()
    opportunity_id = uuid4()
    admin = SimpleNamespace(id=uuid4())
    opportunity = SimpleNamespace(
        id=opportunity_id,
        stage="qualified",
        control_version=2,
        assigned_agent_id=agent_id,
        assigned_operator_id=admin.id,
    )
    assert_owned = AsyncMock()
    transition = AsyncMock(
        return_value=SimpleNamespace(opportunity=opportunity, created=True)
    )
    monkeypatch.setattr(
        "app.routers.admin.commercial.commercial_read_service.assert_owned",
        assert_owned,
    )
    monkeypatch.setattr(
        "app.routers.admin.commercial.opportunity_service.transition_stage",
        transition,
    )

    response = await transition_opportunity_stage(
        agent_id=agent_id,
        opportunity_id=opportunity_id,
        payload=OpportunityStageTransitionRequest(
            target_stage="qualified",
            expected_version=1,
        ),
        idempotency_key="stage-qualified-1",
        correlation_id="request-1",
        admin=admin,
        db=SimpleNamespace(),
    )

    assert_owned.assert_awaited_once()
    transition.assert_awaited_once()
    assert response.control_version == 2
    assert response.created is True


@pytest.mark.asyncio
async def test_quote_request_never_defaults_to_an_issued_or_delivered_state(
    monkeypatch,
) -> None:
    agent_id = uuid4()
    opportunity_id = uuid4()
    admin = SimpleNamespace(id=uuid4())
    quote = SimpleNamespace(
        id=uuid4(),
        status="unavailable",
        state_version=0,
        failure_code="quote_provider_unavailable",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        "app.routers.admin.commercial.commercial_read_service.assert_owned",
        AsyncMock(),
    )
    request_quote = AsyncMock(return_value=SimpleNamespace(request=quote, created=True))
    monkeypatch.setattr(
        "app.routers.admin.commercial.quote_service.request",
        request_quote,
    )

    response = await create_quote_request(
        agent_id=agent_id,
        opportunity_id=opportunity_id,
        payload=QuoteRequestCreateRequest(requirements={"service": "software"}),
        idempotency_key="quote-request-1",
        correlation_id=None,
        admin=admin,
        db=SimpleNamespace(),
    )

    assert response.status == "unavailable"
    assert response.failure_code == "quote_provider_unavailable"
    call = request_quote.await_args.kwargs
    assert call["status"] == "unavailable"
    assert "delivery" not in call
