"""
Agent Platform — Modelo: UsageRecord (cuotas por usuario/período)
"""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedModel


class UsageRecord(TimestampedModel):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint(
            "phone_number", "period_year", "period_month", name="uq_usage_period"
        ),
    )

    # FK al usuario (nullable por compatibilidad con registros pre-migración)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("authorized_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Mantenemos phone_number para queries rápidas y fallback
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=0, nullable=False
    )

    # Relación
    user: Mapped["AuthorizedUser | None"] = relationship(  # noqa: F821
        "AuthorizedUser", back_populates="usage_records"
    )
