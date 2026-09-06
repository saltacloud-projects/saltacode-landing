"""Administration contract tests for conversation-control endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from app.routers.admin.conversation_control import create_operator_message, router
from app.schemas.conversation_control import OperatorMessageRequest


def test_control_endpoints_require_agent_scope_and_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/conversations")
    schema = app.openapi()
    expected = {
        ("/api/admin/conversations/{conversation_id}/control", "get"),
        ("/api/admin/conversations/{conversation_id}/control-events", "get"),
        ("/api/admin/conversations/{conversation_id}/control-transitions", "post"),
        ("/api/admin/conversations/{conversation_id}/operator-messages", "post"),
    }

    for path, method in expected:
        operation = schema["paths"][path][method]
        agent_parameter = next(
            item
            for item in operation["parameters"]
            if item["name"] == "agent_id" and item["in"] == "query"
        )
        assert agent_parameter["required"] is True
        expected_status = "202" if path.endswith("operator-messages") else "200"
        assert expected_status in operation["responses"]

    transition = schema["paths"][
        "/api/admin/conversations/{conversation_id}/control-transitions"
    ]["post"]
    operator_message = schema["paths"][
        "/api/admin/conversations/{conversation_id}/operator-messages"
    ]["post"]
    assert transition["security"] == [{"HTTPBearer": []}]
    assert operator_message["security"] == [{"HTTPBearer": []}]
    idempotency_parameter = next(
        item
        for item in operator_message["parameters"]
        if item["name"] == "Idempotency-Key" and item["in"] == "header"
    )
    assert idempotency_parameter["required"] is True


@pytest.mark.asyncio
async def test_operator_message_endpoint_returns_channel_neutral_delivery_status(
    monkeypatch,
):
    agent_id = uuid4()
    conversation_id = uuid4()
    admin = SimpleNamespace(id=uuid4())
    conversation = SimpleNamespace(
        id=conversation_id,
        agent_id=agent_id,
        control_mode="human",
        control_version=4,
        assigned_admin_id=admin.id,
        control_changed_at=datetime.now(UTC),
        control_reason=None,
    )
    message = SimpleNamespace(id=uuid4())
    delivery = SimpleNamespace(delivery_status="published")
    record = AsyncMock(return_value=(conversation, message, delivery))
    monkeypatch.setattr(
        "app.routers.admin.conversation_control.conversation_control_service.record_operator_message",
        record,
    )

    response = await create_operator_message(
        conversation_id=conversation_id,
        data=OperatorMessageRequest(content="Public web reply", expected_version=4),
        agent_id=agent_id,
        idempotency_key="operator-web-1",
        admin=admin,
        db=SimpleNamespace(),
    )

    assert response.delivery_status == "published"
