"""Administration contract coverage for per-agent panel access grants."""

from fastapi import FastAPI

from app.routers.admin.panel_users import router


def test_panel_user_grant_contract_is_authenticated_and_reversible():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/panel-users")
    paths = app.openapi()["paths"]

    collection = paths["/api/admin/panel-users/{user_id}/agent-grants"]
    mutation = paths["/api/admin/panel-users/{user_id}/agent-grants/{agent_id}"]

    assert collection["get"]["security"] == [{"HTTPBearer": []}]
    assert mutation["put"]["security"] == [{"HTTPBearer": []}]
    assert mutation["delete"]["security"] == [{"HTTPBearer": []}]
    assert "200" in mutation["put"]["responses"]
    assert "204" in mutation["delete"]["responses"]
