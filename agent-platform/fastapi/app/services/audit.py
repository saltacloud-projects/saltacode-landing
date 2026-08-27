"""
Agent Platform — AuditService
Registro y consulta de auditoría de requests del agente.
"""

import logging
import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.schemas.audit import AuditListFilter, AuditLogCreate

logger = logging.getLogger(__name__)


class AuditService:
    async def log(self, db: AsyncSession, data: AuditLogCreate) -> AuditLog:
        # Acepta cualquier string como request_id: UUID válido o string arbitrario.
        # Si no es UUID bien formado, genera un UUID5 determinístico a partir del string.
        try:
            req_id = _uuid.UUID(str(data.request_id))
        except (ValueError, AttributeError, TypeError):
            req_id = _uuid.uuid5(_uuid.NAMESPACE_DNS, str(data.request_id))

        entry = AuditLog(
            request_id=req_id,
            phone_number=data.phone_number,
            channel=data.channel.value,
            input_type=data.input_type.value,
            intent=data.intent,
            source_system=data.source_system.value if data.source_system else None,
            tool_used=data.tool_used,
            duration_ms=data.duration_ms,
            tokens_input=data.tokens_input,
            tokens_output=data.tokens_output,
            cost_estimate=data.cost_estimate,
            status=data.status.value,
            error_code=data.error_code,
            error_message=data.error_message,
            response_preview=data.response_preview[:500]
            if data.response_preview
            else None,
            user_message=data.user_message,
            tool_calls=data.tool_calls,
            extra_metadata=data.extra_metadata,
        )
        db.add(entry)
        await db.flush()
        logger.info(
            "audit_logged",
            extra={
                "request_id": str(req_id),
                "phone": data.phone_number,
                "status": data.status.value,
                "tool": data.tool_used,
            },
        )
        return entry

    async def list_logs(
        self, db: AsyncSession, filters: AuditListFilter
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.created_at.desc())
        if filters.phone_number:
            query = query.where(AuditLog.phone_number == filters.phone_number)
        if filters.status:
            query = query.where(AuditLog.status == filters.status.value)
        if filters.source_system:
            query = query.where(AuditLog.source_system == filters.source_system.value)
        query = query.limit(filters.limit).offset(filters.offset)
        result = await db.execute(query)
        return list(result.scalars().all())


audit_service = AuditService()
