"""Compatibility audit endpoint with role and explicit agent authorization."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.routers.admin.auth import require_agent_permission
from app.schemas.admin import AuditLogAdminOut
from app.services.admin_rbac import AdminPermission
from app.services.audit_read_models import list_audit_records

router = APIRouter(
    tags=["admin-audit"],
    dependencies=[Depends(require_agent_permission(AdminPermission.AUDIT_READ))],
)


@router.get("/", response_model=list[AuditLogAdminOut])
async def list_audit_logs(
    agent_id: UUID,
    phone: str | None = None,
    status: str | None = None,
    source_system: str | None = None,
    tool_used: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogAdminOut]:
    page = await list_audit_records(
        db,
        agent_ids=(agent_id,),
        phone=phone,
        status=status,
        source_system=source_system,
        tool_used=tool_used,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return page.items
