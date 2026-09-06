"""Administration contracts for agent-scoped follow-up operations."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.admin.follow_ups import router

ROOT = "/api/admin/agents/{agent_id}/follow-ups"


def test_follow_up_operations_are_agent_scoped_and_authenticated() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    expected = {
        (f"{ROOT}/", "get"),
        (f"{ROOT}/{{task_id}}", "get"),
        (f"{ROOT}/{{task_id}}/events", "get"),
        (f"{ROOT}/{{task_id}}/cancel", "post"),
        (f"{ROOT}/{{task_id}}/requeue", "post"),
        (f"{ROOT}/{{task_id}}/review-resolution", "post"),
    }

    for path, method in expected:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"HTTPBearer": []}]
        agent_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "agent_id" and parameter["in"] == "path"
        )
        assert agent_parameter["required"] is True

    assert not any(
        "delete" in methods
        for path, methods in schema["paths"].items()
        if "/follow-ups" in path
    )


def test_follow_up_commands_require_idempotency_and_cas() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    for suffix in ("cancel", "requeue", "review-resolution"):
        operation = schema["paths"][f"{ROOT}/{{task_id}}/{suffix}"]["post"]
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["required"] is True

    command = schema["components"]["schemas"]["FollowUpCommandRequest"]
    review = schema["components"]["schemas"]["FollowUpReviewResolutionRequest"]
    assert "expected_version" in command["properties"]
    assert "expected_version" in review["properties"]


def test_follow_up_read_contracts_do_not_expose_sensitive_command_context() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schemas = app.openapi()["components"]["schemas"]
    forbidden = {
        "note",
        "contact_point_id",
        "consent_record_id",
        "correlation_id",
        "idempotency_key",
        "provider_payload",
        "actor_admin_id",
        "actor_worker_id",
    }

    for name in ("FollowUpQueueItemOut", "FollowUpDetailOut", "FollowUpEventOut"):
        assert forbidden.isdisjoint(schemas[name]["properties"])


def test_follow_up_api_rejects_unauthenticated_callers() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)

    response = TestClient(app).get(
        f"/api/admin/agents/{uuid4()}/follow-ups/",
    )

    assert response.status_code == 401
