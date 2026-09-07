"""Contract, authorization and projection regressions for CRM collections."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_db
from app.routers.admin.auth import require_admin
from app.routers.admin.crm import require_crm_scope, router
from app.services.admin_agent_access import (
    AdminAgentAccessService,
    AgentOperationAccess,
)
from app.services.admin_rbac import AdminPermission

RESOURCES = (
    "inbox",
    "opportunities",
    "meetings",
    "follow-ups",
    "deliveries",
    "inbound-jobs",
    "audit",
)


def test_crm_contract_has_no_write_routes_and_exposes_bounded_optional_agent_filters():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/crm")
    schema = app.openapi()
    for resource in RESOURCES:
        path = schema["paths"][f"/api/admin/crm/{resource}"]
        assert set(path) == {"get"}
        operation = path["get"]
        assert operation["security"] == [{"HTTPBearer": []}]
        parameters = {value["name"]: value for value in operation["parameters"]}
        assert not parameters["agent_id"]["required"]
        assert parameters["limit"]["schema"]["maximum"] == 500
        assert parameters["offset"]["schema"]["minimum"] == 0
    for name in ("CrmInboxOut", "CrmFollowUpOut", "CrmMeetingOut", "CrmAuditOut"):
        assert set(schema["components"]["schemas"][name]["required"]).issuperset(
            {"owner_agent_id", "owner_agent_name", "capabilities"}
        )


@pytest.mark.asyncio
async def test_operation_catalog_intersects_role_and_agent_without_profile_read():
    first, second, third = uuid4(), uuid4(), uuid4()
    role_permissions = {
        "conversations.read",
        "conversations.manage",
        "opportunities.read",
    }
    role_service = SimpleNamespace(
        permissions_for_role=AsyncMock(return_value=role_permissions)
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                all=lambda: [
                    (
                        first,
                        "Intake",
                        True,
                        [
                            "conversations.read",
                            "conversations.manage",
                            "runtime.manage",
                        ],
                    ),
                    (second, "Sales", False, ["conversations.read"]),
                    (third, "Hidden", True, ["profiles.read"]),
                ]
            )
        )
    )
    agents = await AdminAgentAccessService(role_service).list_operation_agents(
        db,
        admin_user_id=uuid4(),
        role_key="operator",
        permission=AdminPermission.CONVERSATIONS_READ,
    )
    assert [agent.agent_id for agent in agents] == [first, second]
    assert agents[0].capabilities == frozenset(
        {"conversations.read", "conversations.manage"}
    )
    assert agents[1].capabilities == frozenset({"conversations.read"})
    statement = db.execute.await_args.args[0]
    assert "admin_agent_grants.is_active IS true" in str(statement)


@pytest.mark.asyncio
async def test_role_denial_does_not_load_any_agent_grants():
    db = SimpleNamespace(execute=AsyncMock())
    role_service = SimpleNamespace(
        permissions_for_role=AsyncMock(return_value={"profiles.read"})
    )
    assert (
        await AdminAgentAccessService(role_service).list_operation_agents(
            db,
            admin_user_id=uuid4(),
            role_key="editor",
            permission=AdminPermission.CONVERSATIONS_READ,
        )
        == []
    )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_crm_scope_explicit_foreign_filter_denied_and_empty_scope_is_not_global(
    monkeypatch,
):
    accessible = uuid4()
    monkeypatch.setattr(
        "app.routers.admin.crm.admin_agent_access_service.list_operation_agents",
        AsyncMock(
            return_value=[
                AgentOperationAccess(
                    accessible, "Intake", frozenset({"conversations.read"}), True
                )
            ]
        ),
    )
    dependency = require_crm_scope(AdminPermission.CONVERSATIONS_READ)
    admin = SimpleNamespace(id=uuid4(), role="operator")
    with pytest.raises(HTTPException) as error:
        await dependency(agent_id=uuid4(), admin=admin, db=object())
    assert error.value.status_code == 403
    assert (await dependency(agent_id=None, admin=admin, db=object())).agent_ids == (
        accessible,
    )
    monkeypatch.setattr(
        "app.routers.admin.crm.admin_agent_access_service.list_operation_agents",
        AsyncMock(return_value=[]),
    )
    assert (await dependency(agent_id=None, admin=admin, db=object())).agent_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", RESOURCES)
async def test_every_crm_resource_and_filter_catalog_enforces_role_permission(
    monkeypatch, resource
):
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/crm")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=uuid4(), role="denied"
    )
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_rbac_service.has_permission",
        AsyncMock(return_value=False),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(f"/api/admin/crm/{resource}")).status_code == 403
        assert (
            await client.get(f"/api/admin/crm/{resource}/agents")
        ).status_code == 403


@pytest.mark.asyncio
async def test_legacy_audit_endpoint_rejects_role_only_access_without_agent_grant(
    monkeypatch,
):
    from app.routers.admin.audit import router as audit_router

    app = FastAPI()
    app.include_router(audit_router, prefix="/api/admin/audit")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=uuid4(), role="auditor"
    )
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_agent_access_service.has_permission",
        AsyncMock(return_value=False),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.get("/api/admin/audit/", params={"agent_id": str(uuid4())})
        ).status_code == 403
