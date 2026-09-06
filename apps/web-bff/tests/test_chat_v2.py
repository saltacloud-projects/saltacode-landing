from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.chat_v2.contracts import (
    EventsResponse,
    HistoryMessage,
    HistoryResponse,
    MessageAccepted,
    PrivateMessageRequest,
    PrivateResetRequest,
    ResetResponse,
)
from app.chat_v2.ports import WebChatUnavailableError
from app.config import Settings
from app.main import create_app

ORIGIN = "https://www.saltacode.com.ar"
PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-28"


class FakeWebChatV2Client:
    def __init__(self) -> None:
        self.message_requests: list[tuple[PrivateMessageRequest, str]] = []
        self.history_requests: list[tuple[UUID, str, int]] = []
        self.event_requests: list[tuple[UUID, str, int, int]] = []
        self.reset_requests: list[tuple[PrivateResetRequest, str]] = []
        self.events_pages: list[EventsResponse] = []
        self.failure: Exception | None = None
        self.event_failure_after: int | None = None

    async def accept_message(
        self,
        request: PrivateMessageRequest,
        *,
        correlation_id: str,
    ) -> MessageAccepted:
        self.message_requests.append((request, correlation_id))
        self._raise_failure()
        return MessageAccepted(
            client_message_id=request.client_message_id,
            message_id=uuid4(),
            status="accepted",
            event_cursor=1,
            duplicate=False,
        )

    async def history(
        self,
        *,
        session_id: UUID,
        correlation_id: str,
        limit: int,
    ) -> HistoryResponse:
        self.history_requests.append((session_id, correlation_id, limit))
        self._raise_failure()
        return HistoryResponse(
            status="active",
            control_mode="automated",
            latest_event_id=2,
            messages=[
                HistoryMessage(
                    message_id=uuid4(),
                    client_message_id="browser-message",
                    role="user",
                    content="Necesito una web.",
                    status="received",
                    created_at=datetime.now(UTC),
                )
            ],
        )

    async def events(
        self,
        *,
        session_id: UUID,
        correlation_id: str,
        after: int,
        limit: int,
    ) -> EventsResponse:
        self.event_requests.append((session_id, correlation_id, after, limit))
        if (
            self.event_failure_after is not None
            and len(self.event_requests) > self.event_failure_after
        ):
            raise WebChatUnavailableError("private event polling failed")
        self._raise_failure()
        if self.events_pages:
            return self.events_pages.pop(0)
        return EventsResponse(after=after, next_cursor=after, has_more=False, events=[])

    async def reset_session(
        self,
        request: PrivateResetRequest,
        *,
        correlation_id: str,
    ) -> ResetResponse:
        self.reset_requests.append((request, correlation_id))
        self._raise_failure()
        return ResetResponse(status="active", latest_event_id=0)

    async def aclose(self) -> None:
        return None

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure


def message_payload() -> dict[str, object]:
    return {
        "client_message_id": str(uuid4()),
        "message": "Necesito una solución web.",
        "locale": "es-AR",
        "transcript_consent": True,
        "privacy_version": PRIVACY_VERSION,
    }


def build_client(fake: FakeWebChatV2Client) -> TestClient:
    settings = Settings(
        app_env="test",
        allowed_origins=ORIGIN,
        agent_ai_base_url="http://agent-platform:8001",
        agent_route_key="saltacode-landing",
        chat_v2_poll_seconds=0.001,
        chat_v2_heartbeat_seconds=0.001,
        chat_v2_stream_max_seconds=0.01,
    )
    return TestClient(create_app(settings, web_chat_v2_client=fake))


def test_message_uses_server_owned_route_and_signed_v2_cookie() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        response = client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN, "X-Correlation-ID": "correlation-v2-message"},
        )

    assert response.status_code == 202
    assert response.json().keys() == {
        "client_message_id",
        "message_id",
        "status",
        "event_cursor",
        "duplicate",
    }
    private_request, correlation_id = fake.message_requests[0]
    assert private_request.route_key == "saltacode-landing"
    assert private_request.consent.version == PRIVACY_VERSION
    assert correlation_id == "correlation-v2-message"
    assert "saltacode_chat_session_v2=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Path=/api/v2/chat" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")


def test_history_requires_existing_v2_session_without_creating_cookie() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        response = client.get("/api/v2/chat/history", headers={"Origin": ORIGIN})

    assert response.status_code == 404
    assert response.json()["code"] == "chat_session_not_found"
    assert "set-cookie" not in response.headers
    assert fake.history_requests == []


def test_history_is_scoped_by_server_session_and_route() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        created = client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        response = client.get(
            "/api/v2/chat/history?limit=25",
            headers={"Origin": ORIGIN, "X-Correlation-ID": "correlation-v2-history"},
        )

    assert created.status_code == 202
    assert response.status_code == 200
    session_id, correlation_id, limit = fake.history_requests[0]
    assert session_id == fake.message_requests[0][0].session_id
    assert correlation_id == "correlation-v2-history"
    assert limit == 25
    assert response.json()["messages"][0]["content"] == "Necesito una web."


def test_legacy_upgrade_is_explicit_and_preserves_signed_identity() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        legacy = client.app.state.session_manager.resolve(None)
        client.cookies.set(
            client.app.state.settings.session_cookie_name,
            legacy.cookie_value,
            path="/api/v1/chat",
        )
        response = client.post(
            "/api/v1/chat/session/upgrade",
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 204
    assert response.cookies.get("saltacode_chat_session_v2") == legacy.cookie_value
    assert "Path=/api/v2/chat" in response.headers["set-cookie"]
    assert fake.message_requests == []


def test_invalid_legacy_cookie_does_not_create_v2_identity() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        client.cookies.set(
            "saltacode_chat_session",
            "00000000-0000-4000-8000-000000000000.invalid",
            path="/api/v1/chat",
        )
        response = client.post(
            "/api/v1/chat/session/upgrade",
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 404
    assert "set-cookie" not in response.headers


def test_reset_rotates_cookie_only_after_private_success() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        created = client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        previous_cookie = created.cookies.get("saltacode_chat_session_v2")
        response = client.post(
            "/api/v2/chat/session/reset",
            json={"transcript_consent": True, "privacy_version": PRIVACY_VERSION},
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 200
    replacement_cookie = response.cookies.get("saltacode_chat_session_v2")
    assert replacement_cookie is not None
    assert replacement_cookie != previous_cookie
    reset_request, _ = fake.reset_requests[0]
    assert reset_request.session_id == fake.message_requests[0][0].session_id
    assert reset_request.next_session_id != reset_request.session_id


def test_reset_failure_does_not_rotate_cookie() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        created = client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        previous_cookie = created.cookies.get("saltacode_chat_session_v2")
        fake.failure = WebChatUnavailableError("private detail")
        response = client.post(
            "/api/v2/chat/session/reset",
            json={"transcript_consent": True, "privacy_version": PRIVACY_VERSION},
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 503
    assert "private detail" not in response.text
    assert "set-cookie" not in response.headers
    assert created.cookies.get("saltacode_chat_session_v2") == previous_cookie


def test_events_resume_from_last_event_id() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        fake.events_pages.append(
            EventsResponse.model_validate(
                {
                    "after": 3,
                    "next_cursor": 4,
                    "has_more": False,
                    "events": [
                        {
                            "schema_version": "2",
                            "cursor": 4,
                            "event_type": "chat.message",
                            "occurred_at": datetime.now(UTC),
                            "payload": {"role": "assistant", "content": "Te ayudamos."},
                        }
                    ],
                }
            )
        )
        response = client.get(
            "/api/v2/chat/events",
            headers={"Origin": ORIGIN, "Last-Event-ID": "3"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 4\nevent: chat.message" in response.text
    assert '"content":"Te ayudamos."' in response.text
    assert fake.event_requests[0][2] == 3


def test_events_reject_invalid_cursor_before_private_call() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        response = client.get(
            "/api/v2/chat/events",
            headers={"Origin": ORIGIN, "Last-Event-ID": "03"},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_chat_cursor"
    assert fake.event_requests == []


def test_events_emit_safe_terminal_failure_after_stream_starts() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        fake.event_failure_after = 1
        response = client.get("/api/v2/chat/events", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert "event: chat.error" in response.text
    assert '"code":"chat_temporarily_unavailable"' in response.text
    assert "private event polling failed" not in response.text
    assert "event: chat.done" in response.text


def test_events_fail_as_http_before_stream_headers() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )
        fake.failure = WebChatUnavailableError("private response detail")
        response = client.get("/api/v2/chat/events", headers={"Origin": ORIGIN})

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "private response detail" not in response.text


def test_message_rejects_retired_privacy_before_session_or_private_call() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        response = client.post(
            "/api/v2/chat/messages",
            json=message_payload() | {"privacy_version": "retired-version"},
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "privacy_version_unsupported"
    assert "set-cookie" not in response.headers
    assert fake.message_requests == []


def test_v2_rejects_unlisted_origin_and_allows_sse_cors_header() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        rejected = client.post(
            "/api/v2/chat/messages",
            json=message_payload(),
            headers={"Origin": "https://attacker.example"},
        )
        preflight = client.options(
            "/api/v2/chat/events",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Last-Event-ID",
            },
        )

    assert rejected.status_code == 403
    assert rejected.json()["code"] == "origin_not_allowed"
    assert fake.message_requests == []
    assert preflight.status_code == 200
    assert "last-event-id" in preflight.headers["access-control-allow-headers"].lower()


def test_v1_endpoint_remains_available() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        response = client.post(
            "/api/v1/chat",
            json=message_payload(),
            headers={"Origin": ORIGIN},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_openapi_describes_v2_sse_and_problem_contracts() -> None:
    fake = FakeWebChatV2Client()
    with build_client(fake) as client:
        document = client.get("/openapi.json").json()

    event_operation = document["paths"]["/api/v2/chat/events"]["get"]
    success = event_operation["responses"]["200"]["content"]["text/event-stream"]
    assert success["schema"] == {"type": "string"}
    assert len(success["x-sse-event-schema"]["oneOf"]) == 3
    for status_code in ("400", "403", "404", "422", "429", "503"):
        assert set(event_operation["responses"][status_code]["content"]) == {
            "application/problem+json"
        }
