"""Configurable external integration sources and encrypted credentials."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class IntegrationSource(TimestampedModel):
    __tablename__ = "integration_sources"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), default="http", nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    allowed_hosts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    auth_type: Mapped[str] = mapped_column(String(30), default="none", nullable=False)
    auth_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_headers: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_private_network: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_response_bytes: Mapped[int] = mapped_column(
        Integer, default=2_000_000, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
