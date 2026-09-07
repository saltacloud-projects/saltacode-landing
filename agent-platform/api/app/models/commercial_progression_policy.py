"""Explicit commercial progression, independent of follow-up scheduling limits."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CommercialProgressionPolicy(Base):
    __tablename__ = "commercial_progression_policies"
    __table_args__ = (
        CheckConstraint(
            "quote_request_action IN ('keep_agent', 'handoff')",
            name="ck_commercial_progression_action",
        ),
        CheckConstraint("version >= 1", name="ck_commercial_progression_version"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    quote_request_action: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
