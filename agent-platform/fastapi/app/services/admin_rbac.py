"""Autorización RBAC persistida para el panel administrativo."""

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_role import AdminRole


class AdminPermission(StrEnum):
    ALL = "*"
    DASHBOARD_READ = "dashboard.read"
    PROFILES_READ = "profiles.read"
    KNOWLEDGE_READ = "knowledge.read"
    TOOLS_READ = "tools.read"
    TOOLS_MANAGE = "tools.manage"
    SOURCES_READ = "sources.read"
    SOURCES_MANAGE = "sources.manage"
    USERS_READ = "users.read"
    CONVERSATIONS_READ = "conversations.read"
    CONVERSATIONS_MANAGE = "conversations.manage"
    AUDIT_READ = "audit.read"
    PROMPTLAB_USE = "promptlab.use"
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_MANAGE = "documents.manage"
    DOCUMENTS_TAXONOMY = "documents.taxonomy"
    DOCUMENTS_SETTINGS = "documents.settings"
    PANEL_USERS_MANAGE = "panel_users.manage"


class AdminRbacService:
    async def permissions_for_role(self, db: AsyncSession, role_key: str) -> set[str]:
        permissions = (
            await db.execute(
                select(AdminRole.permissions).where(
                    AdminRole.key == role_key,
                    AdminRole.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if not isinstance(permissions, list):
            return set()
        return {str(value) for value in permissions if isinstance(value, str)}

    async def has_permission(
        self,
        db: AsyncSession,
        *,
        role_key: str,
        permission: str | AdminPermission,
    ) -> bool:
        permissions = await self.permissions_for_role(db, role_key)
        return (
            AdminPermission.ALL.value in permissions or str(permission) in permissions
        )


admin_rbac_service = AdminRbacService()
