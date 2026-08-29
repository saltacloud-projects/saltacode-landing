"""
Agent Platform — Router: Admin Audit
/api/admin/audit/* — consulta de audit logs con filtros.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.authorized_user import AuthorizedUser
from app.routers.admin.auth import require_permission
from app.schemas.admin import AuditLogAdminOut
from app.services.admin_rbac import AdminPermission

router = APIRouter(
    tags=["admin-audit"],
    dependencies=[Depends(require_permission(AdminPermission.AUDIT_READ))],
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
):
    # LEFT JOIN a authorized_users por teléfono para resolver el nombre del
    # usuario (las filas de audit guardan phone_number, no el nombre).
    stmt = (
        select(AuditLog, AuthorizedUser.name)
        .outerjoin(AuthorizedUser, AuditLog.phone_number == AuthorizedUser.phone_number)
        .where(AuditLog.agent_id == agent_id)
        .order_by(AuditLog.created_at.desc())
    )

    if phone:
        stmt = stmt.where(AuditLog.phone_number == phone)
    if status:
        stmt = stmt.where(AuditLog.status == status)
    if source_system:
        stmt = stmt.where(AuditLog.source_system == source_system)
    if tool_used:
        stmt = stmt.where(AuditLog.tool_used == tool_used)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [
        AuditLogAdminOut.from_orm_model(log, user_name=user_name)
        for log, user_name in result.all()
    ]
