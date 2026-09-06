"""Durable evidence that two channel identities may represent one person."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class IdentityLinkClaim(TimestampedModel):
    """Agent-scoped identity assertion without changing either principal."""

    __tablename__ = "identity_link_claims"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "issue_idempotency_key",
            name="uq_identity_link_claim_agent_idempotency",
        ),
        CheckConstraint(
            "source_identity_id <> target_identity_id",
            name="ck_identity_link_claim_distinct_identities",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_status",
        ),
        CheckConstraint(
            "control_version >= 0",
            name="ck_identity_link_claim_control_version",
        ),
        CheckConstraint(
            "proof_token_hash IS NULL OR char_length(proof_token_hash) = 64",
            name="ck_identity_link_claim_proof_hash",
        ),
        CheckConstraint(
            "evidence_sha256 IS NULL OR char_length(evidence_sha256) = 64",
            name="ck_identity_link_claim_evidence_hash",
        ),
        CheckConstraint(
            "status <> 'pending' OR proof_token_hash IS NOT NULL",
            name="ck_identity_link_claim_pending_proof",
        ),
        CheckConstraint(
            "status = 'pending' OR proof_token_hash IS NULL",
            name="ck_identity_link_claim_terminal_proof",
        ),
        CheckConstraint(
            "char_length(issue_command_hash) = 64",
            name="ck_identity_link_claim_issue_command_hash",
        ),
        Index(
            "ix_identity_link_claim_agent_status_updated",
            "agent_id",
            "status",
            "updated_at",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    proof_method: Mapped[str] = mapped_column(String(40), nullable=False)
    proof_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proof_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    proof_consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    created_by_admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    verified_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    issue_command_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class IdentityLinkClaimEvent(Base):
    """Immutable claim transition and idempotency receipt."""

    __tablename__ = "identity_link_claim_events"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "control_version",
            name="uq_identity_link_claim_event_version",
        ),
        UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_identity_link_claim_event_agent_idempotency",
        ),
        CheckConstraint(
            "event_type IN ('issued', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_event_type",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('pending', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_event_from_status",
        ),
        CheckConstraint(
            "to_status IN ('pending', 'verified', 'rejected', 'revoked', 'expired')",
            name="ck_identity_link_claim_event_to_status",
        ),
        CheckConstraint(
            "control_version >= 0",
            name="ck_identity_link_claim_event_control_version",
        ),
        CheckConstraint(
            "char_length(command_hash) = 64",
            name="ck_identity_link_claim_event_command_hash",
        ),
        Index(
            "ix_identity_link_claim_event_claim_created",
            "claim_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_link_claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
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
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
