"""Administration contract coverage for deterministic handoff routes."""

from fastapi import FastAPI

from app.routers.admin.agent_handoff_routes import router

ROOT = "/api/admin/agents/{agent_id}/handoff-routes"


def test_handoff_route_api_is_agent_scoped_authenticated_and_has_no_delete() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    expected = {
        (f"{ROOT}/", "get"),
        (f"{ROOT}/", "post"),
        (f"{ROOT}/{{route_id}}", "get"),
        (f"{ROOT}/{{route_id}}", "patch"),
        (f"{ROOT}/{{route_id}}/deactivate", "post"),
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

    assert "delete" not in schema["paths"][f"{ROOT}/{{route_id}}"]


def test_handoff_contract_exposes_only_supported_triggers_and_cas_fields() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schemas = app.openapi()["components"]["schemas"]
    create = schemas["AgentHandoffRouteCreateRequest"]["properties"]
    update = schemas["AgentHandoffRouteUpdateRequest"]["properties"]
    output = schemas["AgentHandoffRouteOut"]["properties"]

    assert create["trigger"]["enum"] == [
        "quote_requested",
        "manual_escalation",
    ]
    assert "source_agent_id" not in create
    assert "idempotency_key" in create
    assert "expected_version" in update
    assert "idempotency_key" in update
    assert "control_version" in output
    assert "command_hash" not in output


def test_handoff_mutations_keep_idempotency_keys_in_request_bodies() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    schemas = schema["components"]["schemas"]

    for path, method in (
        (f"{ROOT}/", "post"),
        (f"{ROOT}/{{route_id}}", "patch"),
        (f"{ROOT}/{{route_id}}/deactivate", "post"),
    ):
        request_schema = schema["paths"][path][method]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        component = request_schema["$ref"].rsplit("/", maxsplit=1)[-1]
        assert "idempotency_key" in schemas[component]["required"]
