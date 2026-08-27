"""Persistent tool catalog and integration operation binding."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class ToolConfig(TimestampedModel):
    __tablename__ = "tool_registry"

    tool_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    source_system: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integration_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    params_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    cost_category: Mapped[str] = mapped_column(
        String(20), default="low", nullable=False
    )
    handler_path: Mapped[str | None] = mapped_column(String(200))
    result_type: Mapped[str] = mapped_column(String(30), default="text", nullable=False)
    # Platform-managed integrations use ``http_api``. ``native`` is reserved
    # for audited internal capabilities such as cited document delivery.
    handler_kind: Mapped[str] = mapped_column(
        String(20), default="native", server_default="native", nullable=False
    )
    # Declarative HTTP operation metadata (method, path and parameter locations).
    http_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    allowed_channels: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(30), default="read_only", nullable=False
    )
    requires_confirmation: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
