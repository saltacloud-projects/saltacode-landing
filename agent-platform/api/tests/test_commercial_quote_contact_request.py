"""Unit contracts for the native quote contact-request capability."""

import uuid
from types import SimpleNamespace

import pytest

from app.schemas.tools import ToolExecutionContext
from app.services.tools.adapters.commercial_quote_contact_request import (
    CommercialQuoteContactRequestTool,
    register_commercial_quote_contact_request_tool,
)
from app.services.tools.registry import ToolRegistry


def _context(**overrides) -> ToolExecutionContext:
    values = {
        "request_id": "quote-request-1",
        "channel": "web",
        "principal_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "external_subject": "visitor-1",
    }
    values.update(overrides)
    return ToolExecutionContext(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_field", ["principal_id", "conversation_id", "agent_id"]
)
async def test_capability_requires_complete_matching_execution_context(
    missing_field: str,
) -> None:
    tool = CommercialQuoteContactRequestTool()
    params = {
        "title": "Website quote",
        "summary": "A public website for a local business.",
        "preferred_delivery_channel": "email",
    }

    missing_scope = await tool.invoke(params, "quote-request-1", None)
    incomplete_scope = await tool.invoke(
        params,
        "quote-request-1",
        _context(**{missing_field: None}),
    )
    mismatched_request = await tool.invoke(
        params,
        "another-request",
        _context(),
    )
    invalid_channel = await tool.invoke(
        params,
        "quote-request-1",
        _context(channel="api"),
    )

    assert missing_scope.status == "error"
    assert incomplete_scope.status == "error"
    assert mismatched_request.status == "error"
    assert invalid_channel.status == "error"


def test_capability_sanitizes_free_text_and_redacts_direct_identifiers() -> None:
    request = CommercialQuoteContactRequestTool._validate_params(
        {
            "title": "  Website\u0000 quote  ",
            "summary": (
                "Send it to lead@example.com or +54 9 387 555-1212 after review."
            ),
            "preferred_delivery_channel": " EMAIL ",
        }
    )

    assert request.title == "Website quote"
    assert request.summary == ("Send it to [redacted] or [redacted] after review.")
    assert request.preferred_delivery_channel == "email"


def test_existing_request_id_requires_the_same_sanitized_payload() -> None:
    request = CommercialQuoteContactRequestTool._validate_params(
        {
            "title": " Website quote ",
            "summary": "A public website for a local business.",
            "preferred_delivery_channel": "email",
        }
    )
    payload = request.event_payload(request_id="quote-request-1")

    assert CommercialQuoteContactRequestTool._matches_existing_event(
        SimpleNamespace(payload_json=dict(payload)),
        payload,
    )
    assert not CommercialQuoteContactRequestTool._matches_existing_event(
        SimpleNamespace(
            payload_json={**payload, "preferred_delivery_channel": "whatsapp"}
        ),
        payload,
    )


def test_whatsapp_result_requests_contact_and_consent_without_claiming_them() -> None:
    tool = CommercialQuoteContactRequestTool()
    request = tool._validate_params(
        {
            "title": "ERP quote",
            "summary": "The company needs process automation.",
            "preferred_delivery_channel": "whatsapp",
        }
    )

    result = tool._whatsapp_result("quote-request-1", request)

    assert result.status == "success"
    assert result.result["action"] == "request_contact_details_and_consent"
    assert result.result["consent_status"] == "not_captured"
    assert len(result.result["instructions"]) == 3
    assert not {
        "contact_value",
        "email",
        "phone",
        "consent_granted",
    }.intersection(result.result)


def test_capability_registers_without_assigning_an_agent() -> None:
    registry = ToolRegistry()

    register_commercial_quote_contact_request_tool(registry)

    assert isinstance(
        registry.get("commercial_quote_contact_request"),
        CommercialQuoteContactRequestTool,
    )
