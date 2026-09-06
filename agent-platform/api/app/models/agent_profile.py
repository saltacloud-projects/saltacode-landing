"""Configurable agent identity and behavior profile."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # -------------------------------------------------------------------------
    # Identidad
    # -------------------------------------------------------------------------
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # versionado
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -------------------------------------------------------------------------
    # System Prompt modular (secciones independientes)
    # El agent_loop las concatena (identidad + dominio + guardrails) al armar el
    # system prompt; el conocimiento operativo de tools/bases vive en knowledge_blocks.
    # -------------------------------------------------------------------------
    prompt_identity: Mapped[str] = mapped_column(Text)  # Quién es el agente
    prompt_domain: Mapped[str] = mapped_column(Text)  # Sobre qué puede responder
    prompt_guardrails: Mapped[str] = mapped_column(Text)  # Qué NO debe hacer

    # -------------------------------------------------------------------------
    # Mensajes operativos (usados por el pipeline, no por el LLM)
    # -------------------------------------------------------------------------
    unauthorized_message: Mapped[str] = mapped_column(Text)
    error_message: Mapped[str] = mapped_column(Text)

    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
