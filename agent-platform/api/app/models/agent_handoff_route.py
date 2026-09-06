"""Deterministic handoff configuration and immutable command receipts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class AgentHandoffRoute(TimestampedModel):
    """One deterministic target for an agent and supported trigger."""

    __tablename__ = "agent_handoff_routes"
    __table_args__ = (
        UniqueConstraint(
            "source_agent_id",
            "trigger",
            name="uq_agent_handoff_route_source_trigger",
        ),
        CheckConstraint(
            "source_agent_id <> target_agent_id",
            name="ck_agent_handoff_route_distinct_agents",
        ),
        CheckConstraint(
            "trigger IN ('quote_requested', 'manual_escalation')",
            name="ck_agent_handoff_route_trigger",
        ),
        CheckConstraint(
            "control_version >= 0",
            name="ck_agent_handoff_route_control_version",
        ),
        Index(
            "ix_agent_handoff_route_source_active",
            "source_agent_id",
            "is_active",
        ),
    )

    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trigger: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    updated_by_admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class AgentHandoffRouteReceipt(Base):
    """Append-only outcome for an accepted handoff-route command."""

    __tablename__ = "agent_handoff_route_receipts"
    __table_args__ = (
        UniqueConstraint(
            "source_agent_id",
            "idempotency_key",
            name="uq_agent_handoff_receipt_source_idempotency",
        ),
        CheckConstraint(
            "command_type IN ('created', 'updated', 'deactivated')",
            name="ck_agent_handoff_receipt_command_type",
        ),
        CheckConstraint(
            "trigger IN ('quote_requested', 'manual_escalation')",
            name="ck_agent_handoff_receipt_trigger",
        ),
        CheckConstraint(
            "source_agent_id <> target_agent_id",
            name="ck_agent_handoff_receipt_distinct_agents",
        ),
        CheckConstraint(
            "previous_target_agent_id IS NULL OR "
            "source_agent_id <> previous_target_agent_id",
            name="ck_agent_handoff_receipt_distinct_previous_agent",
        ),
        CheckConstraint(
            "control_version >= 0",
            name="ck_agent_handoff_receipt_control_version",
        ),
        CheckConstraint(
            "char_length(command_hash) = 64",
            name="ck_agent_handoff_receipt_command_hash",
        ),
        Index(
            "ix_agent_handoff_receipt_route_created",
            "route_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_handoff_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    command_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_target_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
