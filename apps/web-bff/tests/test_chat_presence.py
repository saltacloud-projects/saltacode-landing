"""Presence uses a bound session and an isolated ephemeral budget, never a message write."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.chat_v2.contracts import (
    ChatPresence,
    EventsResponse,
    HistoryResponse,
    PrivatePresenceRequest,
    TypingState,
)
from app.chat_v2.ports import (
    WebChatBlockedError,
    WebChatPresenceLimitedError,
    WebChatProtocolError,
    WebChatSessionNotFoundError,
    WebChatUnavailableError,
)
from app.config import Settings
from app.main import create_app
from app.ports import RateLimitBackendError
from test_chat_v2 import (
    ORIGIN,
    CountingRateLimiter,
    FakeWebChatV2Client,
    build_client,
    message_payload,
)
from test_chat_v2_client import make_client


class PresenceClient(FakeWebChatV2Client):
    def __init__(self):
        super().__init__()
        self.presence_requests = []

    async def update_presence(self, request, *, correlation_id):
        self.presence_requests.append((request, correlation_id))
        self._raise_failure()
        return TypingState()


def payload(**overrides):
    return {"client_instance_id": str(uuid4()), "sequence": 1, "typing": True, **overrides}


def bind_cookie(client):
    session = client.app.state.session_manager.resolve(None)
    client.cookies.set(client.app.state.settings.session_cookie_v2_name, session.cookie_value)
    return session


def test_existing_session_rejects_non_ascii_signature_without_allocating():
    with build_client(PresenceClient()) as client:
        manager = client.app.state.session_manager
        assert manager.existing(f"{uuid4()}.invalid-é") is None


def test_presence_uses_existing_signed_identity_and_never_allocates_or_rotates_cookie(monkeypatch):
    fake = PresenceClient()
    with build_client(fake) as client:
        session = bind_cookie(client)

        def forbidden(_cookie):
            raise AssertionError("presence cannot allocate a session")

        monkeypatch.setattr(client.app.state.session_manager, "resolve", forbidden)
        body = payload()
        response = client.post(
            "/api/v2/chat/presence",
            json=body,
            headers={"Origin": ORIGIN, "X-Correlation-ID": "presence-test"},
        )
        assert response.status_code == 200
        assert response.json() == {"typing": False, "expires_at": None}
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        private, correlation = fake.presence_requests[0]
        assert private.model_dump(mode="json") == {
            **body,
            "session_id": str(session.session_id),
            "route_key": "saltacode-landing",
        }
        assert correlation == "presence-test"
        assert fake.message_requests == fake.reset_requests == fake.history_requests == []


@pytest.mark.parametrize("cookie", [None, "invalid.signature"])
def test_missing_or_forged_session_never_allocates_or_calls_upstream(cookie, monkeypatch):
    fake = PresenceClient()
    with build_client(fake) as client:
        limiter = CountingRateLimiter()
        client.app.state.presence_rate_limiter = limiter
        if cookie:
            client.cookies.set(client.app.state.settings.session_cookie_v2_name, cookie)
        monkeypatch.setattr(
            client.app.state.session_manager, "resolve", lambda _: pytest.fail("allocated")
        )
        response = client.post("/api/v2/chat/presence", json=payload(), headers={"Origin": ORIGIN})
        assert response.status_code == 404
        assert "set-cookie" not in response.headers
        assert limiter.calls == 0
    assert fake.presence_requests == []


@pytest.mark.parametrize("origin", [None, "https://untrusted.invalid"])
def test_presence_requires_origin_even_with_existing_cookie(origin):
    fake = PresenceClient()
    with build_client(fake) as client:
        bind_cookie(client)
        response = client.post(
            "/api/v2/chat/presence",
            json=payload(),
            headers={"Origin": origin} if origin else {},
        )
        assert response.status_code == 403
    assert fake.presence_requests == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"typing": "true"},
        {"typing": 1},
        {"sequence": True},
        {"sequence": -1},
        {"sequence": 9_007_199_254_740_992},
        {"sequence": 1.5},
        {"client_instance_id": "tab"},
        {"draft": "must not be accepted"},
        {"session_id": str(uuid4())},
        {"route_key": "other"},
    ],
)
def test_presence_rejects_coercion_content_and_browser_owned_routing(overrides):
    fake = PresenceClient()
    with build_client(fake) as client:
        bind_cookie(client)
        response = client.post(
            "/api/v2/chat/presence", json=payload(**overrides), headers={"Origin": ORIGIN}
        )
        assert response.status_code == 422
    assert fake.presence_requests == []


def test_presence_rate_budget_is_configurable_and_separate_from_message_budget():
    fake = PresenceClient()
    settings = Settings(
        app_env="test",
        allowed_origins=ORIGIN,
        agent_route_key="landing",
        rate_limit_requests=1,
        presence_rate_limit_requests=2,
    )
    with TestClient(create_app(settings, web_chat_v2_client=fake)) as client:
        bind_cookie(client)
        statuses = [
            client.post(
                "/api/v2/chat/presence", json=payload(sequence=i), headers={"Origin": ORIGIN}
            ).status_code
            for i in range(3)
        ]
        assert statuses == [200, 200, 429]
        assert (
            client.post(
                "/api/v2/chat/messages", json=message_payload(), headers={"Origin": ORIGIN}
            ).status_code
            == 202
        )
    assert len(fake.presence_requests) == 2


def test_presence_rate_backend_failure_is_closed_and_never_calls_upstream():
    class FailedLimiter(CountingRateLimiter):
        async def check(self, key):
            assert key.startswith("presence:")
            raise RateLimitBackendError()

    fake = PresenceClient()
    with build_client(fake) as client:
        bind_cookie(client)
        client.app.state.presence_rate_limiter = FailedLimiter()
        response = client.post("/api/v2/chat/presence", json=payload(), headers={"Origin": ORIGIN})
        assert response.status_code == 503
    assert fake.presence_requests == []


@pytest.mark.parametrize(
    "error,status",
    [
        (WebChatSessionNotFoundError, 404),
        (WebChatBlockedError, 423),
        (WebChatPresenceLimitedError, 429),
        (WebChatUnavailableError, 503),
    ],
)
def test_private_failures_are_typed_and_do_not_echo_private_details(error, status):
    fake = PresenceClient()
    fake.failure = error("private-detail-must-not-leak")
    with build_client(fake) as client:
        bind_cookie(client)
        response = client.post("/api/v2/chat/presence", json=payload(), headers={"Origin": ORIGIN})
        assert response.status_code == status
        assert "private-detail" not in response.text
        assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_presence_adapter_uses_private_auth_route_correlation_and_no_draft():
    private = PrivatePresenceRequest(**payload(), session_id=uuid4(), route_key="saltacode-landing")

    def handler(request):
        assert request.url.path == "/internal/v2/web/presence"
        assert request.headers["authorization"] == f"Bearer {'x' * 32}"
        assert request.headers["x-correlation-id"] == "presence-test"
        assert json.loads(request.content) == private.model_dump(mode="json")
        return httpx2.Response(200, json={"typing": False, "expires_at": None})

    client = make_client(handler)
    try:
        assert (
            await client.update_presence(private, correlation_id="presence-test") == TypingState()
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error",
    [
        (404, WebChatSessionNotFoundError),
        (423, WebChatBlockedError),
        (429, WebChatPresenceLimitedError),
        (503, WebChatUnavailableError),
        (200, WebChatProtocolError),
    ],
)
async def test_presence_adapter_rejects_status_or_identity_leak(status, error):
    client = make_client(
        lambda _: httpx2.Response(status, json={"typing": False, "actor_admin_id": str(uuid4())})
    )
    private = PrivatePresenceRequest(**payload(), session_id=uuid4(), route_key="saltacode-landing")
    try:
        with pytest.raises(error):
            await client.update_presence(private, correlation_id="test")
    finally:
        await client.aclose()


def test_old_private_server_defaults_presence_off_and_new_private_fields_are_rejected():
    history = dict(status="active", control_mode="human", latest_event_id=0, messages=[])
    events = dict(after=0, next_cursor=0, has_more=False, events=[])
    assert HistoryResponse(**history).presence == ChatPresence()
    assert EventsResponse(**events).presence == ChatPresence()
    with pytest.raises(ValidationError):
        HistoryResponse(
            **history, presence={"operator": {"typing": False, "actor_admin_id": str(uuid4())}}
        )
    for state in (
        {"typing": True},
        {"typing": False, "expires_at": datetime.now(UTC)},
        {"typing": True, "expires_at": "2026-09-07T00:00:00"},
    ):
        with pytest.raises(ValidationError):
            TypingState(**state)


def test_presence_sse_is_ephemeral_renews_expires_and_never_advances_event_cursor():
    fake = PresenceClient()
    expires = datetime.now(UTC) + timedelta(seconds=8)
    for expiry in (expires, expires + timedelta(seconds=3), None):
        fake.events_pages.append(
            EventsResponse(
                after=7,
                next_cursor=7,
                has_more=False,
                events=[],
                presence=ChatPresence(
                    operator=TypingState(typing=expiry is not None, expires_at=expiry)
                ),
            )
        )
    fake.event_failure_after = 3
    with build_client(fake) as client:
        bind_cookie(client)
        response = client.get(
            "/api/v2/chat/events", headers={"Origin": ORIGIN, "Last-Event-ID": "7"}
        )
        frames = [frame for frame in response.text.split("\n\n") if "event: chat.presence" in frame]
        assert len(frames) == 3
        assert all("id:" not in frame for frame in frames)
        states = [json.loads(frame.split("data: ")[1])["presence"]["operator"] for frame in frames]
        assert [state["typing"] for state in states] == [True, True, False]
        assert states[0]["expires_at"] != states[1]["expires_at"]
        assert "event: chat.error" in response.text
    assert all(call[2] == 7 for call in fake.event_requests)
