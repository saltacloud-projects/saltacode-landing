"""
Agent Platform — Router: Admin Config
/api/admin/config/* — estado de configuración del agente.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.routers.admin.auth import require_permission
from app.services.admin_rbac import AdminPermission
from app.services.configuration import configuration_service

router = APIRouter(
    tags=["admin-config"],
    dependencies=[Depends(require_permission(AdminPermission.DASHBOARD_READ))],
)


class ConfigIssueOut(BaseModel):
    level: str
    category: str
    message: str


class ConfigStatusOut(BaseModel):
    is_ready: bool
    issues: list[ConfigIssueOut]


@router.get("/status", response_model=ConfigStatusOut)
async def get_config_status(db: AsyncSession = Depends(get_db)):
    """Estado de configuración del agente: ¿está listo para operar?"""
    status = await configuration_service.check(db)
    return ConfigStatusOut(
        is_ready=status.is_ready,
        issues=[
            ConfigIssueOut(level=i.level, category=i.category, message=i.message)
            for i in status.issues
        ],
    )
