from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response

from saltacode_agent.config import Settings
from saltacode_agent.domain.contracts import ExecutionRequest, ExecutionResponse, ReadinessCheck
from saltacode_agent.transport.http.app import create_app

TOKEN = "test-token-that-is-longer-than-thirty-two-characters"


class ReadyRuntime:
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        return ExecutionResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            output="Accepted by the test runtime.",
        )

    async def check(self) -> tuple[ReadinessCheck, ...]:
        return (ReadinessCheck(name="agent_runtime", ready=True),)


def build_app(*, ready: bool = False):
    settings = Settings(environment="testing", internal_token=TOKEN)
    runtime = ReadyRuntime() if ready else None
    return create_app(settings=settings, runtime=runtime, readiness=runtime)


async def request(method: str, path: str, *, ready: bool = False, **kwargs) -> Response:
    transport = ASGITransport(app=build_app(ready=ready))
    async with AsyncClient(transport=transport, base_url="http://agent.internal") as client:
        return await client.request(method, path, **kwargs)


def execution_payload() -> dict[str, str]:
    return {
        "request_id": str(uuid4()),
        "session_id": str(uuid4()),
        "input": "Quiero conocer los servicios.",
        "locale": "es-AR",
    }


@pytest.mark.asyncio
async def test_liveness_does_not_require_internal_credentials() -> None:
    response = await request("GET", "/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "saltacode-agent"}


@pytest.mark.asyncio
async def test_seed_readiness_fails_closed_until_adapters_are_configured() -> None:
    response = await request("GET", "/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"][0]["name"] == "agent_runtime"


@pytest.mark.asyncio
async def test_execution_requires_internal_bearer_token() -> None:
    response = await request("POST", "/internal/v1/executions", json=execution_payload())

    assert response.status_code == 401
    assert response.json()["detail"] == "internal authentication required"


@pytest.mark.asyncio
async def test_seed_execution_contract_returns_safe_unavailable_error() -> None:
    response = await request(
        "POST",
        "/internal/v1/executions",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=execution_payload(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "agent_runtime_unavailable"
    assert response.json()["retryable"] is True


@pytest.mark.asyncio
async def test_configured_runtime_satisfies_versioned_contract() -> None:
    response = await request(
        "POST",
        "/internal/v1/executions",
        ready=True,
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=execution_payload(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["output"] == "Accepted by the test runtime."
