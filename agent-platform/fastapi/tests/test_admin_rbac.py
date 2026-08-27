"""Pruebas unitarias del RBAC persistente del panel."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_permission
from app.services.admin_rbac import AdminPermission, AdminRbacService


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
async def test_permissions_are_loaded_from_database():
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=ScalarResult(["documents.read", "documents.manage"])
        )
    )
    service = AdminRbacService()
    assert await service.permissions_for_role(db, "document_manager") == {
        "documents.read",
        "documents.manage",
    }


@pytest.mark.asyncio
async def test_wildcard_grants_every_permission():
    db = SimpleNamespace(execute=AsyncMock(return_value=ScalarResult(["*"])))
    service = AdminRbacService()
    assert await service.has_permission(
        db,
        role_key="any-persisted-role",
        permission=AdminPermission.DOCUMENTS_SETTINGS,
    )


@pytest.mark.asyncio
async def test_document_manager_is_denied_other_modules(monkeypatch):
    user = AdminUser(
        email="documents@example.test",
        hashed_password="x",
        name="Documents",
        role="document_manager",
        is_active=True,
        must_change_password=False,
    )
    has_permission = AsyncMock(
        side_effect=lambda _db, *, role_key, permission: (
            str(permission) == "documents.manage"
        )
    )
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_rbac_service.has_permission", has_permission
    )

    allowed = require_permission(AdminPermission.DOCUMENTS_MANAGE)
    assert await allowed(user, object()) is user

    denied = require_permission(AdminPermission.TOOLS_READ)
    with pytest.raises(HTTPException) as exc:
        await denied(user, object())
    assert exc.value.status_code == 403
