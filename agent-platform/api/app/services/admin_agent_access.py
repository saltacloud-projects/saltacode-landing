"""Agent-scoped authorization policy for administration users."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_agent_grant import AdminAgentGrant
from app.models.agent_profile import AgentProfile
from app.services.admin_rbac import (
    AdminPermission,
    AdminRbacService,
    admin_rbac_service,
)

AGENT_SCOPED_PERMISSIONS = (
    AdminPermission.DASHBOARD_READ,
    AdminPermission.PROFILES_READ,
    AdminPermission.KNOWLEDGE_READ,
    AdminPermission.TOOLS_READ,
    AdminPermission.TOOLS_MANAGE,
    AdminPermission.SOURCES_READ,
    AdminPermission.SOURCES_MANAGE,
    AdminPermission.USERS_READ,
    AdminPermission.CONVERSATIONS_READ,
    AdminPermission.CONVERSATIONS_MANAGE,
    AdminPermission.OPPORTUNITIES_READ,
    AdminPermission.OPPORTUNITIES_MANAGE,
    AdminPermission.QUOTES_APPROVE,
    AdminPermission.DELIVERIES_READ,
    AdminPermission.DELIVERIES_REVIEW,
    AdminPermission.AUDIT_READ,
    AdminPermission.PROMPTLAB_USE,
    AdminPermission.DOCUMENTS_READ,
    AdminPermission.DOCUMENTS_MANAGE,
    AdminPermission.DOCUMENTS_TAXONOMY,
    AdminPermission.DOCUMENTS_SETTINGS,
    AdminPermission.RUNTIME_READ,
    AdminPermission.RUNTIME_MANAGE,
)


class AdminAgentAccessService:
    def __init__(self, role_service: AdminRbacService) -> None:
        self._role_service = role_service

    async def permissions_for_agent(
        self,
        db: AsyncSession,
        *,
        admin_user_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> set[str]:
        permissions = (
            await db.execute(
                select(AdminAgentGrant.permissions).where(
                    AdminAgentGrant.admin_user_id == admin_user_id,
                    AdminAgentGrant.agent_id == agent_id,
                    AdminAgentGrant.is_active.is_(True),
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
        admin_user_id: uuid.UUID,
        role_key: str,
        agent_id: uuid.UUID,
        permission: str | AdminPermission,
    ) -> bool:
        if not await self._role_service.has_permission(
            db,
            role_key=role_key,
            permission=permission,
        ):
            return False
        permissions = await self.permissions_for_agent(
            db,
            admin_user_id=admin_user_id,
            agent_id=agent_id,
        )
        return self._allows(permissions, permission)

    async def list_accessible_profiles(
        self,
        db: AsyncSession,
        *,
        admin_user_id: uuid.UUID,
    ) -> list[AgentProfile]:
        rows = (
            await db.execute(
                select(AgentProfile, AdminAgentGrant.permissions)
                .join(
                    AdminAgentGrant,
                    AdminAgentGrant.agent_id == AgentProfile.id,
                )
                .where(
                    AdminAgentGrant.admin_user_id == admin_user_id,
                    AdminAgentGrant.is_active.is_(True),
                )
                .order_by(
                    AgentProfile.is_active.desc(),
                    AgentProfile.updated_at.desc(),
                )
            )
        ).all()
        return [
            profile
            for profile, permissions in rows
            if self._allows(permissions, AdminPermission.PROFILES_READ)
        ]

    async def ensure_grant(
        self,
        db: AsyncSession,
        *,
        admin_user_id: uuid.UUID,
        agent_id: uuid.UUID,
        permissions: Sequence[str | AdminPermission],
        created_by: str,
    ) -> AdminAgentGrant:
        existing = (
            await db.execute(
                select(AdminAgentGrant).where(
                    AdminAgentGrant.admin_user_id == admin_user_id,
                    AdminAgentGrant.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        grant = AdminAgentGrant(
            admin_user_id=admin_user_id,
            agent_id=agent_id,
            permissions=[str(permission) for permission in permissions],
            is_active=True,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(grant)
        return grant

    async def list_grants(
        self,
        db: AsyncSession,
        *,
        admin_user_id: uuid.UUID,
    ) -> list[tuple[AdminAgentGrant, AgentProfile]]:
        rows = await db.execute(
            select(AdminAgentGrant, AgentProfile)
            .join(AgentProfile, AgentProfile.id == AdminAgentGrant.agent_id)
            .where(AdminAgentGrant.admin_user_id == admin_user_id)
            .order_by(AgentProfile.name, AgentProfile.slug)
        )
        return list(rows.all())

    async def grantable_permissions(
        self,
        db: AsyncSession,
        *,
        role_key: str,
    ) -> list[str]:
        role_permissions = await self._role_service.permissions_for_role(db, role_key)
        scoped = [permission.value for permission in AGENT_SCOPED_PERMISSIONS]
        if AdminPermission.ALL.value in role_permissions:
            return [AdminPermission.ALL.value, *scoped]
        return [permission for permission in scoped if permission in role_permissions]

    async def set_grant(
        self,
        db: AsyncSession,
        *,
        admin_user_id: uuid.UUID,
        role_key: str,
        agent_id: uuid.UUID,
        permissions: Sequence[str],
        created_by: str,
    ) -> AdminAgentGrant:
        normalized = list(dict.fromkeys(permissions))
        allowed = set(await self.grantable_permissions(db, role_key=role_key))
        if not normalized or not set(normalized).issubset(allowed):
            raise ValueError("agent grant contains permissions outside the user's role")
        if AdminPermission.ALL.value in normalized and len(normalized) != 1:
            raise ValueError(
                "wildcard agent access cannot be combined with other permissions"
            )
        grant = (
            await db.execute(
                select(AdminAgentGrant)
                .where(
                    AdminAgentGrant.admin_user_id == admin_user_id,
                    AdminAgentGrant.agent_id == agent_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if grant is None:
            grant = AdminAgentGrant(
                admin_user_id=admin_user_id,
                agent_id=agent_id,
                created_by=created_by,
                updated_by=created_by,
            )
            db.add(grant)
        grant.permissions = normalized
        grant.is_active = True
        grant.updated_by = created_by
        await db.flush()
        return grant

    async def revoke_grant(
        self,
        db: AsyncSession,
        *,
        admin_user_id: uuid.UUID,
        agent_id: uuid.UUID,
        updated_by: str,
    ) -> bool:
        grant = (
            await db.execute(
                select(AdminAgentGrant)
                .where(
                    AdminAgentGrant.admin_user_id == admin_user_id,
                    AdminAgentGrant.agent_id == agent_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if grant is None:
            return False
        grant.is_active = False
        grant.updated_by = updated_by
        await db.flush()
        return True

    @staticmethod
    def _allows(
        permissions: Sequence[str] | object,
        permission: str | AdminPermission,
    ) -> bool:
        if not isinstance(permissions, (list, set, tuple)):
            return False
        values = {str(value) for value in permissions if isinstance(value, str)}
        return AdminPermission.ALL.value in values or str(permission) in values


admin_agent_access_service = AdminAgentAccessService(admin_rbac_service)
