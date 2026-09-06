"""Administration contract tests for conversation-control endpoints."""

from __future__ import annotations

from fastapi import FastAPI

from app.routers.admin.conversation_control import router


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
