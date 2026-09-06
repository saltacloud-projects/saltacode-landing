"""
Agent Platform — Modelo: ConversationMessage
Historial de mensajes de cada conversación por usuario.
Nivel 2 de memoria: persistencia completa en PostgreSQL (retención 30 días).
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedModel


class ConversationMessage(TimestampedModel):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_conv_phone_created", "phone_number", "created_at"),)

    # FK al usuario (nullable por compatibilidad con mensajes pre-migración)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("authorized_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Mantenemos phone_number como campo de consulta rápida y fallback
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    role: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(
        String(100)
    )  # solo en mensajes assistant
    tool_used: Mapped[str | None] = mapped_column(String(100))

    # Relación
    user: Mapped["AuthorizedUser | None"] = relationship(  # noqa: F821
        "AuthorizedUser", back_populates="conversation_messages"
    )
