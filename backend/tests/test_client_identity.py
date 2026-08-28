from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.ports import RateLimitDecision
from app.security import client_rate_limit_key


class CapturingRateLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def check(self, key: str) -> RateLimitDecision:
        self.keys.append(key)
        return RateLimitDecision(allowed=True, remaining=19, retry_after_seconds=60)

    async def ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def payload() -> dict[str, str | bool]:
    return {
        "client_message_id": str(uuid4()),
        "message": "test",
        "locale": "es-AR",
        "transcript_consent": True,
        "privacy_version": "saltacode-chat-privacy-2026-08-27",
    }


def test_cloudflare_client_ip_is_validated_and_hashed() -> None:
    limiter = CapturingRateLimiter()
    settings = Settings(app_env="test")

    with TestClient(create_app(settings, rate_limiter=limiter)) as client:
        response = client.post(
            "/api/v1/chat",
            json=payload(),
            headers={"CF-Connecting-IP": "2001:0db8:0:0:0:0:0:1"},
        )

    assert response.status_code == 200
    assert limiter.keys == [client_rate_limit_key("2001:db8::1")]


def test_malformed_cloudflare_client_ip_is_rejected_before_limiter() -> None:
    limiter = CapturingRateLimiter()
    settings = Settings(app_env="test")

    with TestClient(create_app(settings, rate_limiter=limiter)) as client:
        response = client.post(
            "/api/v1/chat",
            json=payload(),
            headers={"CF-Connecting-IP": "198.51.100.1, 127.0.0.1"},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_client_ip"
    assert limiter.keys == []


def test_duplicate_cloudflare_client_ip_headers_are_rejected() -> None:
    limiter = CapturingRateLimiter()
    settings = Settings(app_env="test")

    with TestClient(create_app(settings, rate_limiter=limiter)) as client:
        response = client.post(
            "/api/v1/chat",
            json=payload(),
            headers=[
                ("CF-Connecting-IP", "198.51.100.1"),
                ("CF-Connecting-IP", "198.51.100.2"),
            ],
        )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_client_ip"
    assert limiter.keys == []


def test_asgi_client_is_fallback_when_cloudflare_header_is_absent() -> None:
    limiter = CapturingRateLimiter()
    settings = Settings(app_env="test")

    with TestClient(create_app(settings, rate_limiter=limiter)) as client:
        response = client.post("/api/v1/chat", json=payload())

    assert response.status_code == 200
    assert limiter.keys == [client_rate_limit_key("testclient")]


def test_rotating_session_id_does_not_bypass_client_window() -> None:
    settings = Settings(app_env="test", rate_limit_requests=1)
    headers = {"CF-Connecting-IP": "198.51.100.10"}

    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/chat",
            json=payload(),
            headers=headers,
        )
        second = client.post(
            "/api/v1/chat",
            json=payload(),
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 429


def test_distinct_client_ips_have_isolated_windows() -> None:
    settings = Settings(app_env="test", rate_limit_requests=1)

    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/chat",
            json=payload(),
            headers={"CF-Connecting-IP": "198.51.100.10"},
        )
        second = client.post(
            "/api/v1/chat",
            json=payload(),
            headers={"CF-Connecting-IP": "198.51.100.11"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
