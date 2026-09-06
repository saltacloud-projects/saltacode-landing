"""Administration contract tests for agent-scoped meeting coordination."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.admin.meetings import router

ROOT = "/api/admin/agents/{agent_id}/meetings"


def test_meeting_contract_is_agent_scoped_authenticated_and_non_destructive() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    expected = {
        (f"{ROOT}/", "get"),
        (f"{ROOT}/", "post"),
        (f"{ROOT}/{{meeting_id}}", "get"),
        (f"{ROOT}/{{meeting_id}}/slot-proposals", "post"),
        (f"{ROOT}/{{meeting_id}}/awaiting-response", "post"),
        (f"{ROOT}/{{meeting_id}}/slot-selections", "post"),
        (f"{ROOT}/{{meeting_id}}/manual-schedules", "post"),
        (f"{ROOT}/{{meeting_id}}/reschedule-requests", "post"),
        (f"{ROOT}/{{meeting_id}}/cancellations", "post"),
        (f"{ROOT}/{{meeting_id}}/reviews", "post"),
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
        if "/meetings" in path
    )
    assert not any("calendar" in path for path in schema["paths"])
    summary_schema = schema["components"]["schemas"]["MeetingSummaryOut"]
    assert "opportunity_control_version" in summary_schema["required"]


def test_meeting_commands_require_idempotency_and_state_cas() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    command_paths = [
        f"{ROOT}/",
        f"{ROOT}/{{meeting_id}}/slot-proposals",
        f"{ROOT}/{{meeting_id}}/awaiting-response",
        f"{ROOT}/{{meeting_id}}/slot-selections",
        f"{ROOT}/{{meeting_id}}/manual-schedules",
        f"{ROOT}/{{meeting_id}}/reschedule-requests",
        f"{ROOT}/{{meeting_id}}/cancellations",
        f"{ROOT}/{{meeting_id}}/reviews",
    ]
    for path in command_paths:
        operation = schema["paths"][path]["post"]
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["required"] is True

    state_commands = [
        "MeetingSlotProposalRequest",
        "MeetingTransitionRequest",
        "MeetingSlotSelectionRequest",
        "MeetingManualScheduleRequest",
    ]
    for schema_name in state_commands:
        assert (
            "expected_version"
            in schema["components"]["schemas"][schema_name]["properties"]
        )
    manual = schema["components"]["schemas"]["MeetingManualScheduleRequest"]
    assert "expected_opportunity_version" in manual["properties"]


def test_meeting_api_rejects_unauthenticated_callers() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)

    response = TestClient(app).get(
        f"/api/admin/agents/{uuid4()}/meetings/",
    )

    assert response.status_code == 401
