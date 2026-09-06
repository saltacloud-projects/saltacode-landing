"""
Agent Platform — Schemas de Auditoría
Registro detallado de cada request procesado por el agente.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ChannelEnum, InputTypeEnum, SourceSystemEnum, StatusEnum


class AuditLogCreate(BaseModel):
    agent_id: UUID | None = None
    channel_route_id: UUID | None = None
    request_id: str
    phone_number: str
    channel: ChannelEnum = ChannelEnum.whatsapp
    input_type: InputTypeEnum = InputTypeEnum.text
    intent: str | None = None
    source_system: SourceSystemEnum | None = None
    tool_used: str | None = None
    duration_ms: int | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimate: float = 0.0
    status: StatusEnum
    error_code: str | None = None
    error_message: str | None = None
    response_preview: str | None = None
    user_message: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class AuditLogOut(BaseModel):
    id: str
    agent_id: str | None = None
    channel_route_id: str | None = None
    request_id: str
    phone_number: str
    channel: str
    input_type: str
    intent: str | None = None
    source_system: str | None = None
    tool_used: str | None = None
    duration_ms: int | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimate: float = 0.0
    status: str
    error_code: str | None = None
    error_message: str | None = None
    response_preview: str | None = None
    user_message: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}

    @classmethod
    def from_orm_model(cls, obj) -> "AuditLogOut":
        return cls(
            id=str(obj.id),
            agent_id=str(obj.agent_id) if obj.agent_id else None,
            channel_route_id=str(obj.channel_route_id)
            if obj.channel_route_id
            else None,
            request_id=str(obj.request_id),
            phone_number=obj.phone_number,
            channel=obj.channel,
            input_type=obj.input_type,
            intent=obj.intent,
            source_system=obj.source_system,
            tool_used=obj.tool_used,
            duration_ms=obj.duration_ms,
            tokens_input=obj.tokens_input or 0,
            tokens_output=obj.tokens_output or 0,
            cost_estimate=float(obj.cost_estimate or 0),
            status=obj.status,
            error_code=obj.error_code,
            error_message=obj.error_message,
            response_preview=obj.response_preview,
            user_message=obj.user_message,
            tool_calls=obj.tool_calls or [],
            extra_metadata=obj.extra_metadata or {},
            created_at=obj.created_at,
        )


class AuditListFilter(BaseModel):
    agent_id: UUID | None = None
    channel_route_id: UUID | None = None
    phone_number: str | None = None
    status: StatusEnum | None = None
    source_system: SourceSystemEnum | None = None
    limit: int = 50
    offset: int = 0
