"""Authorized commercial progression configuration for one independent agent."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.commercial_progression import (
    CommercialProgressionOut,
    CommercialProgressionUpdate,
)
from app.services.admin_rbac import AdminPermission
from app.services.commercial.progression_policy import (
    ProgressionPolicyConflictError,
    ProgressionPolicyNotFoundError,
    commercial_progression_service,
)

router = APIRouter(tags=["admin-commercial-progression"])


@router.get("", response_model=CommercialProgressionOut)
async def get_progression_policy(
    agent_id: UUID,
    _admin: AdminUser = Depends(require_agent_permission(AdminPermission.RUNTIME_READ)),
    db: AsyncSession = Depends(get_db),
) -> CommercialProgressionOut:
    return await commercial_progression_service.get(db, agent_id)


@router.put("", response_model=CommercialProgressionOut)
async def configure_progression_policy(
    agent_id: UUID,
    payload: CommercialProgressionUpdate,
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.RUNTIME_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> CommercialProgressionOut:
    try:
        return await commercial_progression_service.configure(
            db, agent_id=agent_id, actor_admin_id=admin.id, request=payload
        )
    except ProgressionPolicyNotFoundError as exc:
        raise HTTPException(404, "Agent not found") from exc
    except ProgressionPolicyConflictError as exc:
        raise HTTPException(
            409, "Progression policy changed; reload before saving"
        ) from exc
