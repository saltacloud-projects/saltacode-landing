from collections.abc import AsyncIterator
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.config import Settings
from app.contracts import AgentRequest, ChatStreamEvent
from app.gateway import HttpAgentGateway
from app.main import create_app


async def collect(events: AsyncIterator[ChatStreamEvent]) -> list[ChatStreamEvent]:
    return [event async for event in events]


def test_app_uses_http_gateway_when_agent_base_url_is_configured() -> None:
    settings = Settings(
        app_env="test",
        agent_ai_base_url="http://agent-ai:8001",
        agent_route_key="saltacode-landing",
    )

    with TestClient(create_app(settings)) as client:
        assert isinstance(client.app.state.agent_gateway, HttpAgentGateway)


@pytest.mark.asyncio
async def test_http_gateway_maps_execution_to_public_events() -> None:
    request = AgentRequest(
        session_id=uuid4(),
        client_message_id=uuid4(),
        message="Necesito un presupuesto.",
        privacy_version="privacy-v1",
    )

    async def handler(http_request: httpx2.Request) -> httpx2.Response:
        assert http_request.url.path == "/internal/v1/executions"
        assert http_request.headers["x-correlation-id"] == "correlation-123"
        assert http_request.headers["authorization"] == f"Bearer {'x' * 32}"
        body = __import__("json").loads(http_request.content)
        assert body == {
            "request_id": str(request.client_message_id),
            "session_id": str(request.session_id),
            "input": request.message,
            "locale": "es-AR",
            "route_key": "saltacode-landing",
            "consent": {"granted": True, "version": "privacy-v1"},
        }
        return httpx2.Response(
            200,
            json={
                "request_id": str(request.client_message_id),
                "session_id": str(request.session_id),
                "status": "completed",
                "output": "Respuesta segura.",
                "tools_used": [],
            },
        )

    gateway = HttpAgentGateway(
        base_url="http://agent-ai:8001",
        route_key="saltacode-landing",
        connect_timeout_seconds=1,
        response_timeout_seconds=10,
        internal_token="x" * 32,
        transport=httpx2.MockTransport(handler),
    )
    try:
        events = await collect(gateway.stream(request, correlation_id="correlation-123"))
    finally:
        await gateway.aclose()

    adapter = TypeAdapter(ChatStreamEvent)
    assert all(adapter.validate_python(event) for event in events)
    assert [event.type for event in events] == ["chat.started", "chat.delta", "chat.done"]
    assert events[1].delta == "Respuesta segura."


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 429, 503])
async def test_http_gateway_safely_maps_private_http_failures(status_code: int) -> None:
    request = AgentRequest(
        session_id=uuid4(),
        client_message_id=uuid4(),
        message="private prompt",
        privacy_version="privacy-v1",
    )

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, text="internal-secret-detail")

    gateway = HttpAgentGateway(
        base_url="http://agent-ai:8001",
        route_key="saltacode-landing",
        connect_timeout_seconds=1,
        response_timeout_seconds=10,
        transport=httpx2.MockTransport(handler),
    )
    try:
        events = await collect(gateway.stream(request, correlation_id="correlation-456"))
    finally:
        await gateway.aclose()

    assert [event.type for event in events] == ["chat.started", "chat.error", "chat.done"]
    assert events[1].code == "agent_unavailable"
    assert "internal-secret-detail" not in events[1].model_dump_json()
    assert events[1].retryable is (status_code in {429, 503})


@pytest.mark.asyncio
async def test_http_gateway_safely_maps_timeout() -> None:
    request = AgentRequest(
        session_id=uuid4(),
        client_message_id=uuid4(),
        message="private prompt",
        privacy_version="privacy-v1",
    )

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timeout", request=http_request)

    gateway = HttpAgentGateway(
        base_url="http://agent-ai:8001",
        route_key="saltacode-landing",
        connect_timeout_seconds=1,
        response_timeout_seconds=1,
        transport=httpx2.MockTransport(handler),
    )
    try:
        events = await collect(gateway.stream(request, correlation_id="correlation-789"))
    finally:
        await gateway.aclose()

    assert [event.type for event in events] == ["chat.started", "chat.error", "chat.done"]
    assert events[1].code == "agent_timeout"
    assert events[1].retryable is True
