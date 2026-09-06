"""Administration API contracts for agent-scoped inbound review."""

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers.admin.channel_inbound import _raise_error, router
from app.services.channel_inbound_review import (
    ChannelInboundIdempotencyConflict,
    ChannelInboundNotFound,
    ChannelInboundVersionConflict,
    InvalidChannelInboundCommand,
)

ROOT = "/api/admin/agents/{agent_id}/inbound-jobs"


def _openapi() -> dict:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    return app.openapi()


def test_inbound_review_routes_are_agent_scoped_and_authenticated() -> None:
    schema = _openapi()
    expected = {
        (f"{ROOT}/", "get"),
        (f"{ROOT}/{{job_id}}", "get"),
        (f"{ROOT}/{{job_id}}/timeline", "get"),
        (f"{ROOT}/{{job_id}}/requeue", "post"),
        (f"{ROOT}/{{job_id}}/cancel", "post"),
        (f"{ROOT}/{{job_id}}/acknowledge", "post"),
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
        if "/inbound-jobs" in path
    )


def test_inbound_review_commands_require_idempotency_and_cas() -> None:
    schema = _openapi()
    for suffix in ("requeue", "cancel", "acknowledge"):
        operation = schema["paths"][f"{ROOT}/{{job_id}}/{suffix}"]["post"]
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["required"] is True

    command = schema["components"]["schemas"]["ChannelInboundCommandRequest"]
    assert command["required"] == ["expected_version"]
    assert command["properties"]["expected_version"]["minimum"] == 0


def test_inbound_review_read_contracts_are_privacy_minimized() -> None:
    schemas = _openapi()["components"]["schemas"]
    forbidden = {
        "provider_message_id",
        "thread_key",
        "route_key_snapshot",
        "payload_ciphertext",
        "payload_hash",
        "legacy_payload_json",
        "provider_sender_id",
        "content",
        "correlation_id",
        "idempotency_key",
        "command_hash",
        "evidence_json",
        "actor_admin_id",
    }

    for name in (
        "ChannelInboundSummaryOut",
        "ChannelInboundDetailOut",
        "ChannelInboundEventOut",
    ):
        assert forbidden.isdisjoint(schemas[name]["properties"])

    event_properties = schemas["ChannelInboundEventOut"]["properties"]
    assert "has_actor_admin" in event_properties


@pytest.mark.parametrize(
    ("error", "expected_status"),
    (
        (ChannelInboundNotFound("missing"), 404),
        (ChannelInboundVersionConflict("stale"), 409),
        (ChannelInboundIdempotencyConflict("collision"), 409),
        (InvalidChannelInboundCommand("invalid"), 422),
    ),
)
def test_inbound_review_errors_have_safe_http_semantics(
    error: Exception,
    expected_status: int,
) -> None:
    with pytest.raises(HTTPException) as raised:
        _raise_error(error)

    assert raised.value.status_code == expected_status


def test_inbound_review_api_rejects_unauthenticated_callers() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)

    response = TestClient(app).get(
        f"/api/admin/agents/{uuid4()}/inbound-jobs/",
    )

    assert response.status_code == 401
