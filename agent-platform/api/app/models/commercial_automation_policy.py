"""Persisted, fail-closed policy for commercial automation execution."""

from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class CommercialAutomationPolicy(TimestampedModel):
    """Agent-owned execution policy; absence or default state means disabled."""

    __tablename__ = "commercial_automation_policies"
    __table_args__ = (
        CheckConstraint(
            "allowed_kinds <@ ARRAY['commercial_follow_up', "
            "'meeting_coordination', 'proposal_reminder']::varchar[]",
            name="ck_commercial_automation_policy_allowed_kinds",
        ),
        CheckConstraint(
            "char_length(btrim(timezone)) > 0",
            name="ck_commercial_automation_policy_timezone",
        ),
        CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="ck_commercial_automation_policy_quiet_pair",
        ),
        CheckConstraint(
            "quiet_hours_start IS NULL OR quiet_hours_start <> quiet_hours_end",
            name="ck_commercial_automation_policy_quiet_range",
        ),
        CheckConstraint(
            "min_interval_seconds >= 0 AND max_attempts > 0 "
            "AND max_daily_tasks > 0 AND max_pending_tasks > 0",
            name="ck_commercial_automation_policy_limits",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_commercial_automation_policy_version",
        ),
        UniqueConstraint(
            "agent_id",
            name="uq_commercial_automation_policy_agent",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    allowed_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)),
        default=list,
        server_default=text("'{}'::varchar[]"),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        server_default="UTC",
        nullable=False,
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time(), nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time(), nullable=True)
    min_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=3600,
        server_default="3600",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    max_daily_tasks: Mapped[int] = mapped_column(
        Integer,
        default=25,
        server_default="25",
        nullable=False,
    )
    max_pending_tasks: Mapped[int] = mapped_column(
        Integer,
        default=100,
        server_default="100",
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
