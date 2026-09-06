"""
Agent Platform — Modelo: KnowledgeBlock

Capa de conocimiento PERSISTIDA y editable del agente. Permite personalizar lo
"variable" (hints de esquema de APIs, regiones, reglas de dominio) desde
la DB, sin tocar código ni hacer redeploy.

Separación estático/variable:
  - CÓDIGO: la lógica de composición (builder) y un fallback seguro.
  - DATOS (esta tabla): el contenido editable que se inyecta al prompt.

El agent_loop arma el system prompt combinando el AgentProfile (identidad) + los
KnowledgeBlock activos (conocimiento de dominio/bases) + lógica temporal (código).
"""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class KnowledgeBlock(TimestampedModel):
    __tablename__ = "knowledge_blocks"

    # Clave estable para referenciar el bloque desde el código (ej: "inventory_api",
    # "policies", "catalog"). Unique.
    key: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
    # Título legible para administración.
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    # Contenido que se inyecta al prompt del agente.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Permite activar/desactivar un bloque sin borrarlo.
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Orden de composición (menor primero).
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
