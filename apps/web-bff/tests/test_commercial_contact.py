from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.chat_v2.contracts import (
    CommercialContactAccepted,
    EventsResponse,
    HistoryResponse,
    MessageAccepted,
    PrivateCommercialContactRequest,
    PrivateMessageRequest,
    PrivateResetRequest,
    ResetResponse,
)
from app.chat_v2.ports import (
    WebChatBlockedError,
    WebChatConflictError,
    WebChatSessionNotFoundError,
    WebChatUnavailableError,
    WebChatUnprocessableError,
)
from app.config import Settings
from app.main import create_app
from app.ports import RateLimitDecision

ORIGIN = "https://www.saltacode.com.ar"
PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-28"


class FakeWebChatV2Client:
    def __init__(self) -> None:
        self.commercial_requests: list[tuple[PrivateCommercialContactRequest, str]] = []
        self.failure: Exception | None = None

    async def accept_commercial_contact(
        self,
        request: PrivateCommercialContactRequest,
        *,
        correlation_id: str,
    ) -> CommercialContactAccepted:
        self.commercial_requests.append((request, correlation_id))
        if self.failure is not None:
            raise self.failure
        return CommercialContactAccepted(
            opportunity_id=uuid4(),
            target_agent_id=uuid4(),
            status="accepted",
        )

    async def accept_message(
        self,
        request: PrivateMessageRequest,
        *,
        correlation_id: str,
    ) -> MessageAccepted:
        raise AssertionError((request, correlation_id))

    async def history(self, **kwargs) -> HistoryResponse:
        raise AssertionError(kwargs)

    async def events(self, **kwargs) -> EventsResponse:
        raise AssertionError(kwargs)

    async def reset_session(
        self,
        request: PrivateResetRequest,
        *,
        correlation_id: str,
    ) -> ResetResponse:
        raise AssertionError((request, correlation_id))

    async def aclose(self) -> None:
        return None


class DenyingRateLimiter:
    async def check(self, _key: str) -> RateLimitDecision:
        return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=31)

    async def ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def commercial_payload() -> dict[str, object]:
    return {
        "client_request_id": str(uuid4()),
        "locale": "es-AR",
        "title": "Sitio web para empresa industrial",
        "summary": "Necesita catálogo, contacto comercial y soporte.",
        "contact_kind": "email",
        "contact_value": "lead@example.com",
        "preferred_delivery_channel": "email",
        "quote_delivery_consent": True,
        "commercial_follow_up_consent": False,
        "privacy_version": PRIVACY_VERSION,
    }


def build_client(
    fake: FakeWebChatV2Client,
    *,
    rate_limiter=None,
) -> Iterator[TestClient]:
    settings = Settings(
        app_env="test",
        allowed_origins=ORIGIN,
        agent_ai_base_url="http://agent-platform:8001",
        agent_route_key="saltacode-landing",
    )
    return TestClient(
        create_app(
            settings,
            rate_limiter=rate_limiter,
            web_chat_v2_client=fake,
        )
    )


def set_signed_session(client: TestClient) -> UUID:
    session = client.app.state.session_manager.resolve(None)
    client.cookies.set(
        client.app.state.settings.session_cookie_v2_name,
        session.cookie_value,
        path="/api/v2/chat",
    )
    return session.session_id


def test_commercial_contact_uses_server_owned_session_route_and_policy() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        session_id = set_signed_session(client)
        response = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload(),
            headers={"Origin": ORIGIN, "X-Correlation-ID": "commercial-correlation"},
        )

    assert response.status_code == 202
    assert response.json().keys() == {"opportunity_id", "target_agent_id", "status"}
    private_request, correlation_id = fake.commercial_requests[0]
    assert private_request.session_id == session_id
    assert private_request.route_key == "saltacode-landing"
    assert private_request.policy_version == PRIVACY_VERSION
    assert private_request.contact_value == "lead@example.com"
    assert correlation_id == "commercial-correlation"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")


def test_commercial_contact_requires_existing_valid_signed_session() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        missing = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload(),
            headers={"Origin": ORIGIN},
        )
        client.cookies.set(
            "saltacode_chat_session_v2",
            "00000000-0000-4000-8000-000000000000.invalid",
            path="/api/v2/chat",
        )
        invalid = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload(),
            headers={"Origin": ORIGIN},
        )

    assert missing.status_code == 404
    assert invalid.status_code == 404
    assert missing.json()["code"] == "chat_session_not_found"
    assert invalid.json()["code"] == "chat_session_not_found"
    assert fake.commercial_requests == []


@pytest.mark.parametrize(
    "payload_patch",
    [
        {"contact_value": "not-an-email"},
        {
            "contact_kind": "phone",
            "contact_value": "+5493875551234",
            "preferred_delivery_channel": "email",
        },
        {
            "contact_kind": "phone",
            "contact_value": "03875551234",
            "preferred_delivery_channel": "whatsapp",
        },
        {"quote_delivery_consent": False},
        {"session_id": str(uuid4())},
        {"route_key": "browser-controlled"},
    ],
)
def test_commercial_contact_rejects_invalid_or_browser_owned_fields(
    payload_patch: dict[str, object],
) -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        set_signed_session(client)
        response = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload() | payload_patch,
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "request_validation_failed"
    assert fake.commercial_requests == []


def test_commercial_contact_rejects_retired_privacy_before_private_call() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        set_signed_session(client)
        response = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload() | {"privacy_version": "retired-version"},
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "privacy_version_unsupported"
    assert fake.commercial_requests == []


def test_commercial_contact_enforces_origin_and_shared_abuse_limit() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake, rate_limiter=DenyingRateLimiter()) as client:
        set_signed_session(client)
        origin_rejected = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload(),
            headers={"Origin": "https://attacker.example"},
        )
        rate_rejected = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload(),
            headers={"Origin": ORIGIN},
        )

    assert origin_rejected.status_code == 403
    assert origin_rejected.json()["code"] == "origin_not_allowed"
    assert rate_rejected.status_code == 429
    assert rate_rejected.headers["retry-after"] == "31"
    assert fake.commercial_requests == []


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (WebChatSessionNotFoundError("private detail"), 404, "chat_session_not_found"),
        (WebChatConflictError("private detail"), 409, "commercial_contact_conflict"),
        (WebChatUnprocessableError("private detail"), 422, "commercial_contact_rejected"),
        (WebChatBlockedError("private detail"), 423, "commercial_contact_blocked"),
        (WebChatUnavailableError("private detail"), 503, "commercial_service_unavailable"),
    ],
)
def test_commercial_contact_maps_private_failures_without_leaking_details(
    failure: Exception,
    status_code: int,
    code: str,
) -> None:
    fake = FakeWebChatV2Client()
    fake.failure = failure
    with build_client(fake) as client:
        set_signed_session(client)
        response = client.post(
            "/api/v2/chat/commercial-contact",
            json=commercial_payload(),
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code
    assert "private detail" not in response.text


def test_openapi_documents_commercial_contact_contract_and_failures() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        operation = client.get("/openapi.json").json()["paths"]["/api/v2/chat/commercial-contact"][
            "post"
        ]

    assert operation["responses"]["202"]["content"]["application/json"]
    for status_code in ("400", "403", "404", "409", "422", "423", "429", "503"):
        assert set(operation["responses"][status_code]["content"]) == {"application/problem+json"}
