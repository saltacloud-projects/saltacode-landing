"""
Agent Platform — Modelo: AuditLog (auditoría por request)
"""

import uuid
from decimal import Decimal

from sqlalchemy import UUID, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class AuditLog(TimestampedModel):
    __tablename__ = "audit_logs"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, default=uuid.uuid4
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", nullable=False)
    input_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    intent: Mapped[str | None] = mapped_column(String(100))
    source_system: Mapped[str | None] = mapped_column(String(30))
    tool_used: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=0, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    response_preview: Mapped[str | None] = mapped_column(String(500))
    # La consulta original del usuario (texto del mensaje entrante).
    user_message: Mapped[str | None] = mapped_column(Text)
    # Detalle de tools efectivamente invocadas: lista de {tool, args, status}.
    tool_calls: Mapped[list | None] = mapped_column(JSONB, default=list)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
