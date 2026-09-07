"""HTTP query boundaries and exact preservation of public author classification."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.admin.crm import router as crm_router
from app.routers.admin.inbox_filters import inbox_message_filters
from app.routers.admin.operator_inbox import router as scoped_router
from app.schemas.operator_inbox import InboxMessageFilters
from app.services.message_authorship import message_author_type
from app.services.web_chat_v2 import WebChatV2Service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"last_message_from": "2026-09-07T00:00:00"},
        {"last_message_before": "2026-09-07"},
        {"last_message_from": "1788739200"},
        {"last_message_from": "2026-09-07 00:00:00Z"},
        {"last_message_from": "2026-09-07T00:00:00+25:00"},
        {"last_message_from": "2026-02-30T00:00:00Z"},
        {
            "last_message_from": "2026-09-07T03:00:00Z",
            "last_message_before": "2026-09-07T00:00:00-03:00",
        },
        {
            "last_message_from": "2026-09-08T00:00:00Z",
            "last_message_before": "2026-09-07T00:00:00Z",
        },
        {"search": "x" * 121},
    ],
)
async def test_message_filter_query_rejects_naive_non_rfc3339_and_invalid_range(params):
    app = FastAPI()

    @app.get("/filters")
    def endpoint(filters: InboxMessageFilters = Depends(inbox_message_filters)):
        return filters

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/filters", params=params)).status_code == 422


def test_aware_offsets_and_trimmed_literal_search_are_preserved():
    filters = InboxMessageFilters(
        last_message_from="2026-09-07T00:00:00-03:00",
        last_message_before="2026-09-08T03:00:00Z",
        search="  %_\\/literal  ",
    )
    assert filters.last_message_from.astimezone(UTC) == datetime(
        2026, 9, 7, 3, tzinfo=UTC
    )
    assert filters.search == "%_\\/literal"
    assert InboxMessageFilters(search="  ").search is None


@pytest.mark.parametrize("role", ["user", "assistant", "system", "tool", "legacy"])
@pytest.mark.parametrize("origin", [None, "operator", "other"])
@pytest.mark.parametrize("has_execution", [False, True])
def test_shared_authorship_preserves_exact_public_history_semantics(
    role, origin, has_execution
):
    expected = (
        "visitor"
        if role == "user"
        else "operator"
        if origin == "operator"
        else "agent"
        if has_execution
        else "unknown"
    )
    message = SimpleNamespace(role=role, metadata_json={"origin": origin})
    assert message_author_type(role, origin, has_execution) == expected
    assert WebChatV2Service._author_type(message, has_execution) == expected


def test_both_inbox_routes_expose_same_optional_filters_without_public_contract_changes():
    app = FastAPI()
    app.include_router(crm_router, prefix="/api/admin/crm")
    app.include_router(scoped_router, prefix="/api/admin/agents/{agent_id}/inbox")
    schema = app.openapi()
    for path in ("/api/admin/crm/inbox", "/api/admin/agents/{agent_id}/inbox/"):
        operation = schema["paths"][path]["get"]
        params = {item["name"]: item for item in operation["parameters"]}
        assert set(params) >= {
            "last_message_from",
            "last_message_before",
            "search",
            "unread_only",
            "updated_after",
            "updated_before",
        }
        assert all(
            not params[name]["required"]
            for name in (
                "last_message_from",
                "last_message_before",
                "search",
                "unread_only",
            )
        )
        assert operation["security"] == [{"HTTPBearer": []}]
    fields = schema["components"]["schemas"]["InboxConversationOut"]["properties"]
    assert set(fields) >= {
        "last_message_at",
        "last_message_preview",
        "last_message_author_type",
    }
