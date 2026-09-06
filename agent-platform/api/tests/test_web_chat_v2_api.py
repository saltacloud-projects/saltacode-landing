"""HTTP contract tests for the private durable web-chat API."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.config import settings
from app.dependencies import get_db
from app.routers.executions import router as executions_v1_router
from app.routers.web_chat_v2 import router
from app.schemas.web_chat_v2 import (
    WebHistoryResponse,
    WebMessageAccepted,
    WebSessionResetResponse,
)
from app.services.web_chat_v2 import (
    WebChatRequestConflictError,
    WebChatSessionBlockedError,
    WebChatV2Service,
)


class _Database:
    def __init__(self, commit_error: Exception | None = None) -> None:
        self.commits = 0
        self.commit_error = commit_error

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error


def _app(db: _Database) -> FastAPI:
    app = FastAPI()
    app.include_router(executions_v1_router)
    app.include_router(router)

    async def db_override():
        yield db

    app.dependency_overrides[get_db] = db_override
    return app


def _message_payload() -> dict:
    return {
        "session_id": str(uuid4()),
        "client_message_id": str(uuid4()),
        "route_key": "saltacode-web",
        "content": "I need a website",
        "locale": "es-AR",
        "consent": {"granted": True, "version": "privacy-v1"},
    }


def test_public_event_projection_does_not_expose_target_agent_identity():
    event = SimpleNamespace(
        sequence=7,
        event_type="commercial.opportunity.created",
        created_at=datetime.now(timezone.utc),
        payload_json={
            "opportunity_id": str(uuid4()),
            "status": "accepted",
            "target_agent_id": str(uuid4()),
        },
    )

    projected = WebChatV2Service._public_event(event)

    assert projected.payload.keys() == {"opportunity_id", "status"}


@pytest.mark.asyncio
async def test_v2_requires_internal_bearer_and_keeps_v1_registered(monkeypatch):
    from app.routers import web_chat_v2 as module

    db = _Database()
    service = SimpleNamespace(
        accept_message=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(module, "web_chat_v2_service", service)
    app = _app(db)
    paths = {route.path for route in app.routes}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        missing = await client.post(
            "/internal/v2/web/messages", json=_message_payload()
        )
        invalid = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(),
            headers={"Authorization": "Bearer wrong-key"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert "/internal/v1/executions" in paths
    assert "/internal/v2/web/messages" in paths


@pytest.mark.asyncio
async def test_message_returns_202_only_after_durable_commit(monkeypatch):
    from app.routers import web_chat_v2 as module

    payload = _message_payload()
    db = _Database()

    class Service:
        async def accept_message(self, request_db, request):
            assert request_db is db
            return WebMessageAccepted(
                client_message_id=request.client_message_id,
                message_id=uuid4(),
                event_cursor=1,
                duplicate=False,
            )

    monkeypatch.setattr(module, "web_chat_v2_service", Service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
    ) as client:
        response = await client.post("/internal/v2/web/messages", json=payload)

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["duplicate"] is False
    assert db.commits == 1


@pytest.mark.asyncio
async def test_message_does_not_return_202_when_commit_fails(monkeypatch):
    from app.routers import web_chat_v2 as module

    db = _Database(RuntimeError("database commit failed"))

    class Service:
        async def accept_message(self, _db, request):
            return WebMessageAccepted(
                client_message_id=request.client_message_id,
                message_id=uuid4(),
                event_cursor=1,
                duplicate=False,
            )

    monkeypatch.setattr(module, "web_chat_v2_service", Service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db), raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
    ) as client:
        response = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(),
        )

    assert response.status_code == 500
    assert db.commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (WebChatRequestConflictError("conflict"), 409),
        (WebChatSessionBlockedError("blocked"), 423),
    ],
)
async def test_message_maps_conflict_and_blocked_without_committing(
    monkeypatch,
    failure,
    expected_status,
):
    from app.routers import web_chat_v2 as module

    db = _Database()

    class Service:
        async def accept_message(self, _db, _request):
            raise failure

    monkeypatch.setattr(module, "web_chat_v2_service", Service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
    ) as client:
        response = await client.post(
            "/internal/v2/web/messages",
            json=_message_payload(),
        )

    assert response.status_code == expected_status
    assert db.commits == 0


@pytest.mark.asyncio
async def test_history_and_reset_responses_do_not_expose_internal_ids(monkeypatch):
    from app.routers import web_chat_v2 as module

    session_id = uuid4()
    next_session_id = uuid4()
    now = datetime.now(timezone.utc)
    db = _Database()

    class Service:
        async def history(self, _db, **_kwargs):
            return WebHistoryResponse(
                status="active",
                control_mode="automated",
                latest_event_id=2,
                messages=[
                    {
                        "message_id": uuid4(),
                        "client_message_id": str(uuid4()),
                        "role": "user",
                        "content": "Hello",
                        "status": "accepted",
                        "created_at": now,
                    }
                ],
            )

        async def reset_session(self, _db, _request):
            return WebSessionResetResponse(latest_event_id=0)

    monkeypatch.setattr(module, "web_chat_v2_service", Service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.fastapi_api_key}"},
    ) as client:
        history = await client.get(
            "/internal/v2/web/history",
            params={"session_id": str(session_id), "route_key": "saltacode-web"},
        )
        reset = await client.post(
            "/internal/v2/web/session/reset",
            json={
                "session_id": str(session_id),
                "next_session_id": str(next_session_id),
                "route_key": "saltacode-web",
                "consent": {"granted": True, "version": "privacy-v1"},
            },
        )

    assert history.status_code == 200
    assert reset.status_code == 200
    assert "conversation_id" not in history.text
    assert "agent_id" not in history.text
    assert "principal_id" not in history.text
    assert reset.json() == {
        "status": "active",
        "latest_event_id": 0,
    }
    assert db.commits == 1
