"""Administration contract tests for the agent-scoped operator inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.routers.admin.operator_inbox import create_inbox_operator_message, router
from app.schemas.conversation_control import OperatorMessageRequest


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
