"""Focused authorization tests for administrator-to-agent grants."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.bootstrap import bootstrap_admin_agent_grant
from app.models.admin_agent_grant import AdminAgentGrant
from app.routers.admin.auth import require_agent_permission
from app.services.admin_agent_access import (
    AGENT_SCOPED_PERMISSIONS,
    AdminAgentAccessService,
)
from app.services.admin_rbac import AdminPermission


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


def test_meeting_permissions_are_explicit_and_not_added_to_legacy_grants():
    legacy_grant = ["opportunities.read", "opportunities.manage"]

    assert AdminPermission.MEETINGS_READ in AGENT_SCOPED_PERMISSIONS
    assert AdminPermission.MEETINGS_MANAGE in AGENT_SCOPED_PERMISSIONS
    assert not AdminAgentAccessService._allows(
        legacy_grant,
        AdminPermission.MEETINGS_READ,
    )
    assert AdminAgentAccessService._allows(["*"], AdminPermission.MEETINGS_MANAGE)


@pytest.mark.asyncio
async def test_agent_permission_requires_role_and_active_grant():
    role_service = SimpleNamespace(has_permission=AsyncMock(return_value=True))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=ScalarResult(["profiles.read"]))
    )
    service = AdminAgentAccessService(role_service)

    assert await service.has_permission(
        db,
        admin_user_id=uuid4(),
        role_key="viewer",
        agent_id=uuid4(),
        permission=AdminPermission.PROFILES_READ,
    )


@pytest.mark.asyncio
async def test_role_denial_short_circuits_agent_grant_lookup():
    role_service = SimpleNamespace(has_permission=AsyncMock(return_value=False))
    db = SimpleNamespace(execute=AsyncMock())
    service = AdminAgentAccessService(role_service)

    assert not await service.has_permission(
        db,
        admin_user_id=uuid4(),
        role_key="viewer",
        agent_id=uuid4(),
        permission=AdminPermission.PROFILES_READ,
    )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_listing_excludes_grants_without_profile_read_access():
    visible = SimpleNamespace(id=uuid4())
    hidden = SimpleNamespace(id=uuid4())
    role_service = SimpleNamespace()
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=RowsResult(
                [
                    (visible, ["*"]),
                    (hidden, ["conversations.read"]),
                ]
            )
        )
    )
    service = AdminAgentAccessService(role_service)

    assert await service.list_accessible_profiles(
        db,
        admin_user_id=uuid4(),
    ) == [visible]


@pytest.mark.asyncio
async def test_agent_dependency_denies_a_foreign_agent(monkeypatch):
    admin = SimpleNamespace(id=uuid4(), role="admin")
    access = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_agent_access_service.has_permission",
        access,
    )
    dependency = require_agent_permission(AdminPermission.CONVERSATIONS_READ)

    with pytest.raises(HTTPException) as error:
        await dependency(str(uuid4()), admin, object())

    assert error.value.status_code == 403
    assert error.value.detail == "No tiene acceso a este agente"


@pytest.mark.asyncio
async def test_agent_dependency_accepts_an_already_parsed_uuid(monkeypatch):
    agent_id = uuid4()
    admin = SimpleNamespace(id=uuid4(), role="admin")
    access = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_agent_access_service.has_permission",
        access,
    )
    dependency = require_agent_permission(AdminPermission.OPPORTUNITIES_READ)

    assert await dependency(agent_id, admin, object()) is admin
    assert access.await_args.kwargs["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_bootstrap_grant_is_limited_to_resolved_admin_and_profile(monkeypatch):
    admin = SimpleNamespace(id=uuid4())
    profile = SimpleNamespace(id=uuid4())
    ensure_grant = AsyncMock()
    monkeypatch.setattr(
        "app.bootstrap.admin_agent_access_service.ensure_grant",
        ensure_grant,
    )

    await bootstrap_admin_agent_grant(object(), admin, profile)

    ensure_grant.assert_awaited_once_with(
        ANY,
        admin_user_id=admin.id,
        agent_id=profile.id,
        permissions=[AdminPermission.ALL],
        created_by="bootstrap",
    )


@pytest.mark.asyncio
async def test_bootstrap_does_not_reactivate_an_existing_revoked_grant():
    grant = AdminAgentGrant(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        permissions=["*"],
        is_active=False,
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=ScalarResult(grant)),
        add=Mock(),
    )
    service = AdminAgentAccessService(SimpleNamespace())

    result = await service.ensure_grant(
        db,
        admin_user_id=grant.admin_user_id,
        agent_id=grant.agent_id,
        permissions=[AdminPermission.ALL],
        created_by="bootstrap",
    )

    assert result is grant
    assert result.is_active is False
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_grant_update_reactivates_and_replaces_permissions():
    grant = AdminAgentGrant(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        permissions=["profiles.read"],
        is_active=False,
    )
    role_service = SimpleNamespace(permissions_for_role=AsyncMock(return_value={"*"}))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=ScalarResult(grant)),
        add=Mock(),
        flush=AsyncMock(),
    )
    service = AdminAgentAccessService(role_service)

    result = await service.set_grant(
        db,
        admin_user_id=grant.admin_user_id,
        role_key="admin",
        agent_id=grant.agent_id,
        permissions=["opportunities.read", "opportunities.manage"],
        created_by="actor",
    )

    assert result is grant
    assert result.is_active is True
    assert result.permissions == ["opportunities.read", "opportunities.manage"]
    assert result.updated_by == "actor"
    db.add.assert_not_called()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_grant_update_rejects_permissions_outside_the_role():
    role_service = SimpleNamespace(
        permissions_for_role=AsyncMock(return_value={"opportunities.read"})
    )
    db = SimpleNamespace(execute=AsyncMock())
    service = AdminAgentAccessService(role_service)

    with pytest.raises(ValueError, match="outside the user's role"):
        await service.set_grant(
            db,
            admin_user_id=uuid4(),
            role_key="sales_viewer",
            agent_id=uuid4(),
            permissions=["quotes.approve"],
            created_by="actor",
        )

    db.execute.assert_not_awaited()
