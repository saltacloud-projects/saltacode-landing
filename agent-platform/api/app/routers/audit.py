"""
Agent Platform — Router: Audit
/internal/audit/* — registro y consulta de auditoría de requests
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.dependencies import get_db
from app.schemas.audit import AuditListFilter, AuditLogCreate, AuditLogOut
from app.services.audit import audit_service

router = APIRouter(tags=["audit"], dependencies=[Depends(require_api_key)])


@router.post("/log", response_model=AuditLogOut, status_code=201)
async def log_event(data: AuditLogCreate, db: AsyncSession = Depends(get_db)):
    """Registrar un evento de auditoría."""
    entry = await audit_service.log(db, data)
    await db.commit()
    await db.refresh(entry)
    return AuditLogOut.from_orm_model(entry)


@router.get("/logs", response_model=list[AuditLogOut])
async def list_logs(
    phone_number: str | None = None,
    status: str | None = None,
    source_system: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    from app.schemas.common import SourceSystemEnum, StatusEnum

    filters = AuditListFilter(
        phone_number=phone_number,
        status=StatusEnum(status) if status else None,
        source_system=SourceSystemEnum(source_system) if source_system else None,
        limit=min(limit, 200),
        offset=offset,
    )
    entries = await audit_service.list_logs(db, filters)
    return [AuditLogOut.from_orm_model(e) for e in entries]
