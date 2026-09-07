"""Agent-attributed audit collections with stable, bounded pagination."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.schemas.admin import AuditLogAdminOut


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: list[AuditLogAdminOut]
    total: int
    owner_agent_ids: dict[UUID, UUID]


async def list_audit_records(
    db: AsyncSession,
    *,
    agent_ids: tuple[UUID, ...],
    phone: str | None = None,
    status: str | None = None,
    source_system: str | None = None,
    tool_used: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AuditPage:
    # Null legacy ownership is not inferred from telephone or another agent.
    statement = select(AuditLog).where(AuditLog.agent_id.in_(agent_ids))
    for value, column in (
        (phone, AuditLog.phone_number),
        (status, AuditLog.status),
        (source_system, AuditLog.source_system),
        (tool_used, AuditLog.tool_used),
    ):
        if value:
            statement = statement.where(column == value)
    if date_from:
        statement = statement.where(AuditLog.created_at >= date_from)
    if date_to:
        statement = statement.where(AuditLog.created_at <= date_to)
    total = int(
        (
            await db.execute(select(func.count()).select_from(statement.subquery()))
        ).scalar_one()
    )
    logs = (
        (
            await db.execute(
                statement.order_by(AuditLog.created_at.desc(), AuditLog.id)
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return AuditPage(
        items=[AuditLogAdminOut.from_orm_model(log) for log in logs],
        total=total,
        owner_agent_ids={log.id: log.agent_id for log in logs},
    )
