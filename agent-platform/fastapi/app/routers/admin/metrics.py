"""
Agent Platform — Router: Admin Metrics
/api/admin/metrics/* — dashboard con métricas operativas.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.conversation_message import ConversationMessage
from app.models.message_status import MessageStatus
from app.routers.admin.auth import require_permission
from app.schemas.admin import MetricsDashboard, ToolUsageStat
from app.services.admin_rbac import AdminPermission

router = APIRouter(
    tags=["admin-metrics"],
    dependencies=[Depends(require_permission(AdminPermission.DASHBOARD_READ))],
)


@router.get("/dashboard", response_model=MetricsDashboard)
async def dashboard(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)
    d1 = now - timedelta(hours=24)

    # Messages today / 7d / 30d
    messages_today = await _count_messages(db, today_start)
    messages_7d = await _count_messages(db, d7)
    messages_30d = await _count_messages(db, d30)

    # Active users (unique phones) last 7d
    active_users = (
        await db.execute(
            select(func.count(func.distinct(ConversationMessage.phone_number))).where(
                ConversationMessage.created_at >= d7
            )
        )
    ).scalar() or 0

    # Errors last 24h
    errors_24h = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.status == "error", AuditLog.created_at >= d1)
        )
    ).scalar() or 0

    # Top tools (last 30d)
    top_tools_result = await db.execute(
        select(AuditLog.tool_used, func.count().label("cnt"))
        .where(AuditLog.tool_used.isnot(None), AuditLog.created_at >= d30)
        .group_by(AuditLog.tool_used)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_tools = [
        ToolUsageStat(tool_name=row[0], count=row[1]) for row in top_tools_result.all()
    ]

    # Delivery stats (all time, from message_statuses)
    delivery_result = await db.execute(
        select(MessageStatus.status, func.count()).group_by(MessageStatus.status)
    )
    delivery_stats = {row[0]: row[1] for row in delivery_result.all()}

    return MetricsDashboard(
        messages_today=messages_today,
        messages_7d=messages_7d,
        messages_30d=messages_30d,
        active_users_7d=active_users,
        errors_24h=errors_24h,
        top_tools=top_tools,
        delivery_stats=delivery_stats,
    )


async def _count_messages(db: AsyncSession, since: datetime) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ConversationMessage)
        .where(
            ConversationMessage.created_at >= since,
            ConversationMessage.role == "user",
        )
    )
    return result.scalar() or 0
