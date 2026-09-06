"""WhatsApp channel access grant and document scope."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedModel


class AuthorizedUser(TimestampedModel):
    __tablename__ = "authorized_users"

    phone_number: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)

    has_all_area_access: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Nivel 3 de memoria: resumen compactado del historial del usuario
    conversation_summary: Mapped[str | None] = mapped_column(Text)
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relaciones
    conversation_messages: Mapped[list["ConversationMessage"]] = relationship(  # noqa: F821
        "ConversationMessage",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
