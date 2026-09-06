"""Contract tests for agent-scoped outbound delivery review."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI

from app.routers.admin.deliveries import router
from app.services.outbound_delivery_review import OutboundDeliveryReviewService

ROOT = "/api/admin/agents/{agent_id}/deliveries"


def test_delivery_review_contract_is_agent_scoped_read_only_and_authenticated():
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()

    for path in (f"{ROOT}/", f"{ROOT}/{{delivery_id}}"):
        operation = schema["paths"][path]["get"]
        assert operation["security"] == [{"HTTPBearer": []}]
        agent_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "agent_id" and parameter["in"] == "path"
        )
        assert agent_parameter["required"] is True

    list_parameters = {
        parameter["name"]
        for parameter in schema["paths"][f"{ROOT}/"]["get"]["parameters"]
    }
    assert {"channel", "status", "conversation_id"} <= list_parameters
    assert all(
        set(methods) == {"get"}
        for path, methods in schema["paths"].items()
        if path.startswith(ROOT)
    )


def test_delivery_contract_never_exposes_payload_destination_or_internal_actor_ids():
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schemas = app.openapi()["components"]["schemas"]
    serialized = str(schemas)

    assert "payload_json" not in serialized
    assert "destination" not in serialized
    assert "idempotency_key" not in serialized
    assert "payload_hash" not in serialized
    assert "worker_id" not in serialized
    assert "actor_id" not in serialized


def test_delivery_summary_masks_provider_reference_and_describes_fifo_impact():
    now = datetime.now(UTC)
    message = SimpleNamespace(
        id=uuid4(),
        conversation_id=uuid4(),
        channel_route_id=uuid4(),
        chat_message_id=None,
        status="delivery_unknown",
        kind="text",
        sender_type="automation",
        sequence=1,
        correlation_id="correlation-safe-1",
        provider_message_id="provider-secret-reference-123456",
        created_at=now,
        updated_at=now,
    )

    result = OutboundDeliveryReviewService._summary_out(
        message,
        "whatsapp",
        1,
        "provider_timeout",
        2,
    )

    assert result.provider_reference == "…123456"
    assert "provider-secret" not in result.provider_reference
    assert result.is_fifo_blocking is True
    assert result.blocked_message_count == 2
