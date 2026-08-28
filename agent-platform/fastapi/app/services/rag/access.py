"""Resolución fail-closed del alcance documental por usuario."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_resource_binding import (
    AgentAuthorizedUserArea,
    AgentAuthorizedUserBinding,
    AgentOrganizationAreaBinding,
)
from app.models.authorized_user import AuthorizedUser
from app.models.rag import AuthorizedUserArea, OrganizationArea


async def get_user_area_ids(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    agent_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    if user_id is None:
        return set()
    if agent_id is not None:
        binding = (
            await db.execute(
                select(AgentAuthorizedUserBinding).where(
                    AgentAuthorizedUserBinding.agent_id == agent_id,
                    AgentAuthorizedUserBinding.user_id == user_id,
                    AgentAuthorizedUserBinding.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if binding is None:
            return set()
        if binding.has_all_area_access:
            result = await db.execute(
                select(OrganizationArea.id)
                .join(
                    AgentOrganizationAreaBinding,
                    AgentOrganizationAreaBinding.area_id == OrganizationArea.id,
                )
                .where(
                    AgentOrganizationAreaBinding.agent_id == agent_id,
                    OrganizationArea.is_active == True,  # noqa: E712
                )
            )
            return set(result.scalars().all())
        result = await db.execute(
            select(AgentAuthorizedUserArea.area_id)
            .join(
                OrganizationArea,
                OrganizationArea.id == AgentAuthorizedUserArea.area_id,
            )
            .where(
                AgentAuthorizedUserArea.agent_id == agent_id,
                AgentAuthorizedUserArea.user_id == user_id,
                OrganizationArea.is_active == True,  # noqa: E712
            )
        )
        return set(result.scalars().all())

    user = (
        await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.id == user_id, AuthorizedUser.is_active.is_(True)
            )  # noqa: E712
        )
    ).scalar_one_or_none()
    if user is None:
        return set()
    if user.has_all_area_access:
        result = await db.execute(
            select(OrganizationArea.id).where(OrganizationArea.is_active == True)  # noqa: E712
        )
        return set(result.scalars().all())
    result = await db.execute(
        select(AuthorizedUserArea.area_id)
        .join(OrganizationArea, OrganizationArea.id == AuthorizedUserArea.area_id)
        .where(
            AuthorizedUserArea.user_id == user.id,
            OrganizationArea.is_active == True,  # noqa: E712
        )
    )
    return set(result.scalars().all())


async def get_general_area_id(db: AsyncSession) -> uuid.UUID | None:
    return (
        await db.execute(
            select(OrganizationArea.id).where(
                OrganizationArea.is_general == True,  # noqa: E712
                OrganizationArea.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
