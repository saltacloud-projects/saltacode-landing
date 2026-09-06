"""Administration contract tests for the agent-scoped operator inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException

from app.routers.admin.operator_inbox import (
    assign_inbox_automation_agent,
    create_inbox_operator_message,
    router,
)
from app.schemas.conversation_control import OperatorMessageRequest
from app.schemas.operator_inbox import AutomationAssignmentRequest


def test_inbox_contract_keeps_agent_scope_in_the_path_and_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/agents/{agent_id}/inbox")
    schema = app.openapi()
    expected = {
        ("/api/admin/agents/{agent_id}/inbox/", "get", "200"),
        ("/api/admin/agents/{agent_id}/inbox/operators", "get", "200"),
        (
            "/api/admin/agents/{agent_id}/inbox/{conversation_id}",
            "get",
            "200",
        ),
        (
            "/api/admin/agents/{agent_id}/inbox/{conversation_id}/control-transitions",
            "post",
            "200",
        ),
        (
            "/api/admin/agents/{agent_id}/inbox/{conversation_id}/operator-messages",
            "post",
            "202",
        ),
        (
            "/api/admin/agents/{agent_id}/inbox/{conversation_id}/automation-assignments",
            "get",
            "200",
        ),
        (
            "/api/admin/agents/{agent_id}/inbox/{conversation_id}/automation-assignments",
            "post",
            "200",
        ),
    }

    for path, method, expected_status in expected:
        operation = schema["paths"][path][method]
        agent_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "agent_id" and parameter["in"] == "path"
        )
        assert agent_parameter["required"] is True
        assert operation["security"] == [{"HTTPBearer": []}]
        assert expected_status in operation["responses"]

    operator_message = schema["paths"][
        "/api/admin/agents/{agent_id}/inbox/{conversation_id}/operator-messages"
    ]["post"]
    idempotency_parameter = next(
        parameter
        for parameter in operator_message["parameters"]
        if parameter["name"] == "Idempotency-Key" and parameter["in"] == "header"
    )
    assert idempotency_parameter["required"] is True

    assignment = schema["paths"][
        "/api/admin/agents/{agent_id}/inbox/{conversation_id}/automation-assignments"
    ]["post"]
    assignment_headers = {
        parameter["name"]: parameter
        for parameter in assignment["parameters"]
        if parameter["in"] == "header"
    }
    assert assignment_headers["Idempotency-Key"]["required"] is True
    assert assignment_headers["X-Correlation-ID"]["required"] is True


def test_inbox_list_exposes_operational_filters_without_an_delete_operation():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/agents/{agent_id}/inbox")
    schema = app.openapi()
    operation = schema["paths"]["/api/admin/agents/{agent_id}/inbox/"]["get"]
    parameter_names = {parameter["name"] for parameter in operation["parameters"]}

    assert {
        "channel",
        "control_mode",
        "status",
        "assigned_admin_id",
        "unassigned_only",
        "updated_after",
        "updated_before",
    } <= parameter_names
    assert not any(
        "delete" in methods
        for path, methods in schema["paths"].items()
        if "/inbox" in path
    )


def test_inbox_contract_exposes_routing_and_acting_agents_without_secrets():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/agents/{agent_id}/inbox")
    schemas = app.openapi()["components"]["schemas"]

    conversation = schemas["InboxConversationOut"]["properties"]
    receipt = schemas["AutomationAssignmentReceiptOut"]["properties"]
    assignment_event = schemas["AutomationAssignmentEventOut"]["properties"]
    assignment_request = schemas["AutomationAssignmentRequest"]["properties"]

    assert {"routing_agent", "automation_agent", "automation_version"} <= set(
        conversation
    )
    assert set(receipt) == {
        "event_id",
        "applied",
        "duplicate",
        "automation_agent_id",
        "automation_version",
    }
    assert assignment_request["trigger"]["enum"] == [
        "operator_assignment",
        "operator_reassignment",
    ]
    forbidden = {
        "command_hash",
        "idempotency_key",
        "correlation_id",
        "prompt_identity",
        "credentials",
    }
    assert forbidden.isdisjoint(assignment_event)


@pytest.mark.asyncio
async def test_inbox_operator_message_returns_published_web_delivery_status(
    monkeypatch,
):
    agent_id = uuid4()
    conversation_id = uuid4()
    admin = SimpleNamespace(id=uuid4())
    conversation = SimpleNamespace(
        id=conversation_id,
        agent_id=agent_id,
        control_mode="human",
        control_version=2,
        assigned_admin_id=admin.id,
        control_changed_at=datetime.now(UTC),
        control_reason=None,
    )
    message = SimpleNamespace(id=uuid4())
    delivery = SimpleNamespace(delivery_status="published")
    record = AsyncMock(return_value=(conversation, message, delivery))
    monkeypatch.setattr(
        "app.routers.admin.operator_inbox.conversation_control_service.record_operator_message",
        record,
    )

    response = await create_inbox_operator_message(
        agent_id=agent_id,
        conversation_id=conversation_id,
        payload=OperatorMessageRequest(content="Public web reply", expected_version=2),
        idempotency_key="operator-web-1",
        admin=admin,
        db=SimpleNamespace(),
    )

    assert response.delivery_status == "published"


@pytest.mark.asyncio
async def test_assignment_requires_target_runtime_access_without_enumeration(
    monkeypatch,
):
    target_access = AsyncMock(return_value=False)
    assignment = AsyncMock()
    monkeypatch.setattr(
        "app.routers.admin.operator_inbox.admin_agent_access_service.has_permission",
        target_access,
    )
    monkeypatch.setattr(
        "app.routers.admin.operator_inbox.conversation_automation_assignment_service.assign",
        assignment,
    )
    target_agent_id = uuid4()

    with pytest.raises(HTTPException) as error:
        await assign_inbox_automation_agent(
            agent_id=uuid4(),
            conversation_id=uuid4(),
            payload=AutomationAssignmentRequest(
                target_agent_id=target_agent_id,
                expected_automation_version=0,
                trigger="operator_assignment",
            ),
            idempotency_key="assignment-1",
            correlation_id="correlation-1",
            admin=SimpleNamespace(id=uuid4(), role="operator"),
            db=SimpleNamespace(),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Conversation or agent not found"
    assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_forwards_scoped_cas_and_returns_minimal_receipt(monkeypatch):
    routing_agent_id = uuid4()
    target_agent_id = uuid4()
    conversation_id = uuid4()
    admin = SimpleNamespace(id=uuid4(), role="operator")
    event = SimpleNamespace(
        id=uuid4(),
        to_automation_agent_id=target_agent_id,
        automation_version=3,
    )
    target_access = AsyncMock(return_value=True)
    assignment = AsyncMock(
        return_value=SimpleNamespace(
            event=event,
            applied=True,
            duplicate=False,
        )
    )
    monkeypatch.setattr(
        "app.routers.admin.operator_inbox.admin_agent_access_service.has_permission",
        target_access,
    )
    monkeypatch.setattr(
        "app.routers.admin.operator_inbox.conversation_automation_assignment_service.assign",
        assignment,
    )

    response = await assign_inbox_automation_agent(
        agent_id=routing_agent_id,
        conversation_id=conversation_id,
        payload=AutomationAssignmentRequest(
            target_agent_id=target_agent_id,
            expected_automation_version=2,
            trigger="operator_reassignment",
            reason="Operator prepared the specialist before resuming automation.",
        ),
        idempotency_key="assignment-2",
        correlation_id="correlation-2",
        admin=admin,
        db=SimpleNamespace(),
    )

    target_access.assert_awaited_once()
    assert target_access.await_args.kwargs["agent_id"] == target_agent_id
    assert target_access.await_args.kwargs["permission"] == "runtime.manage"
    assignment.assert_awaited_once()
    assert assignment.await_args.kwargs == {
        "conversation_id": conversation_id,
        "routing_agent_id": routing_agent_id,
        "target_agent_id": target_agent_id,
        "expected_automation_version": 2,
        "actor_agent_id": None,
        "actor_admin_id": admin.id,
        "trigger": "operator_reassignment",
        "opportunity_id": None,
        "correlation_id": "correlation-2",
        "idempotency_key": "assignment-2",
        "reason": "Operator prepared the specialist before resuming automation.",
    }
    assert response.model_dump() == {
        "event_id": event.id,
        "applied": True,
        "duplicate": False,
        "automation_agent_id": target_agent_id,
        "automation_version": 3,
    }
