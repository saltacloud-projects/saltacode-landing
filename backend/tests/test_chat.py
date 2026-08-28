from uuid import uuid4

from fastapi.testclient import TestClient


def payload() -> dict[str, str]:
    return {
        "client_message_id": str(uuid4()),
        "message": "Necesito información sobre sus servicios.",
        "locale": "es-AR",
        "transcript_consent": True,
        "privacy_version": "saltacode-chat-privacy-2026-08-28",
    }


def test_chat_exposes_typed_sse_boundary(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json=payload(),
        headers={
            "Origin": "https://www.saltacode.com.ar",
            "X-Correlation-ID": "test-correlation-123",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-correlation-id"] == "test-correlation-123"
    assert "event: chat.started" in response.text
    assert "event: chat.error" in response.text
    assert '"code":"agent_unavailable"' in response.text
    assert "event: chat.done" in response.text
    assert "Necesito información" not in response.text


def test_chat_rejects_unlisted_origin_with_safe_problem(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json=payload(),
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "origin_not_allowed"
    assert "correlation_id" in response.json()


def test_invalid_request_does_not_echo_validation_input(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "private-value-that-must-not-be-echoed"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_failed"
    assert "private-value" not in response.text


def test_chat_rejects_unsupported_privacy_version_before_session_and_rate_limit() -> None:
    from app.config import Settings
    from app.main import create_app

    settings = Settings(app_env="test", rate_limit_requests=1)
    unsupported_payload = payload() | {"privacy_version": "retired-private-version"}
    with TestClient(create_app(settings)) as client:
        rejected = client.post("/api/v1/chat", json=unsupported_payload)
        accepted = client.post("/api/v1/chat", json=payload())

    assert rejected.status_code == 400
    assert rejected.headers["content-type"].startswith("application/problem+json")
    assert rejected.json()["code"] == "privacy_version_unsupported"
    assert "retired-private-version" not in rejected.text
    assert "set-cookie" not in rejected.headers
    assert accepted.status_code == 200


def test_chat_rate_limit_is_enforced() -> None:
    from app.config import Settings
    from app.main import create_app

    settings = Settings(app_env="test", rate_limit_requests=1)
    chat_payload = payload()
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/v1/chat", json=chat_payload)
        second = client.post("/api/v1/chat", json=chat_payload)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"]
    assert second.json()["code"] == "rate_limit_exceeded"


def test_openapi_describes_sse_and_problem_contracts(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/chat"]["post"]
    success = operation["responses"]["200"]["content"]["text/event-stream"]

    assert set(operation["responses"]["200"]["content"]) == {"text/event-stream"}
    assert success["schema"] == {"type": "string"}
    assert "x-sse-event-schema" in success
    for status in ("400", "403", "422", "429", "503"):
        assert set(operation["responses"][status]["content"]) == {"application/problem+json"}


def test_chat_session_is_owned_by_signed_http_only_cookie(client: TestClient) -> None:
    first = client.post("/api/v1/chat", json=payload())
    cookie = first.cookies.get("saltacode_chat_session")
    assert first.status_code == 200
    assert cookie is not None
    assert "HttpOnly" in first.headers["set-cookie"]

    second = client.post("/api/v1/chat", json=payload())
    assert second.cookies.get("saltacode_chat_session") == cookie


def test_forged_chat_session_is_rotated(client: TestClient) -> None:
    client.cookies.set("saltacode_chat_session", "00000000-0000-4000-8000-000000000000.invalid")
    response = client.post("/api/v1/chat", json=payload())
    assert response.status_code == 200
    assert (
        response.cookies.get("saltacode_chat_session")
        != "00000000-0000-4000-8000-000000000000.invalid"
    )
