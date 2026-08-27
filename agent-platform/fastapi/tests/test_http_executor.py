from __future__ import annotations

import httpx
import pytest

from app.models.integration_source import IntegrationSource
from app.services.http_executor import RestrictedHttpExecutor, SourceRequestError


def _source(**overrides) -> IntegrationSource:
    values = {
        "name": "Local test source",
        "slug": "local-test",
        "source_type": "http",
        "base_url": "http://127.0.0.1",
        "allowed_hosts": ["127.0.0.1"],
        "auth_type": "none",
        "auth_config": {},
        "default_headers": {},
        "is_active": True,
        "is_public": False,
        "verify_tls": False,
        "allow_private_network": True,
        "timeout_seconds": 2,
        "max_response_bytes": 4096,
    }
    values.update(overrides)
    return IntegrationSource(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_executor_supports_declared_http_methods(method: str) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    executor = RestrictedHttpExecutor(transport=httpx.MockTransport(handler))
    try:
        result = await executor.execute(
            _source(),
            method=method,
            path="/v1/items",
            query={"limit": 5},
            json_body={"name": "example"} if method not in {"GET", "DELETE"} else None,
            idempotency_key="request-1",
        )
    finally:
        await executor.aclose()

    assert result.status_code == 200
    assert seen[0].method == method
    assert seen[0].headers["idempotency-key"] == "request-1"


@pytest.mark.asyncio
async def test_executor_enforces_streamed_response_limit() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2048)

    executor = RestrictedHttpExecutor(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(SourceRequestError, match="size limit") as exc:
            await executor.execute(
                _source(max_response_bytes=1024), method="GET", path="/"
            )
    finally:
        await executor.aclose()
    assert exc.value.code == "source_response_too_large"


@pytest.mark.asyncio
async def test_executor_blocks_private_destination_without_explicit_opt_in() -> None:
    executor = RestrictedHttpExecutor(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    )
    try:
        with pytest.raises(SourceRequestError) as exc:
            await executor.execute(
                _source(
                    base_url="https://127.0.0.1",
                    verify_tls=True,
                    allow_private_network=False,
                ),
                method="GET",
                path="/",
            )
    finally:
        await executor.aclose()
    assert exc.value.code == "source_network_denied"
