"""Commercial contact points and append-only consent evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampedModel


class Contact(TimestampedModel):
    """Commercial profile attached one-to-one to an existing principal."""

    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('provisional', 'active', 'archived')",
            name="ck_contact_status",
        ),
        UniqueConstraint("principal_id", name="uq_contact_principal"),
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="provisional",
        server_default="provisional",
        nullable=False,
    )
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(160), nullable=True)

    points: Mapped[list[ContactPoint]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
    )


class ContactPoint(TimestampedModel):
    """Encrypted voluntary contact detail with deterministic keyed lookup."""

    __tablename__ = "contact_points"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('email', 'phone')",
            name="ck_contact_point_kind",
        ),
        CheckConstraint(
            "verification_status IN ('unverified', 'pending', 'verified', 'revoked')",
            name="ck_contact_point_verification_status",
        ),
        CheckConstraint(
            "char_length(lookup_hmac) = 64",
            name="ck_contact_point_lookup_hmac",
        ),
        CheckConstraint(
            "char_length(ciphertext) > 40 AND ciphertext <> masked_value",
            name="ck_contact_point_ciphertext",
        ),
        CheckConstraint(
            "verification_status != 'verified' OR verified_at IS NOT NULL",
            name="ck_contact_point_verified_at",
        ),
        CheckConstraint(
            "verification_status != 'revoked' OR revoked_at IS NOT NULL",
            name="ck_contact_point_revoked_at",
        ),
        UniqueConstraint(
            "contact_id",
            "kind",
            "lookup_hmac",
            name="uq_contact_point_value",
        ),
        Index("ix_contact_point_kind_lookup", "kind", "lookup_hmac"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    lookup_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    masked_value: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20),
        default="unverified",
        nullable=False,
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    contact: Mapped[Contact] = relationship(back_populates="points")


class ConsentRecord(Base):
    """Immutable grant or revoke evidence for one explicit purpose."""

    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('conversation_storage', 'quote_delivery', "
            "'commercial_follow_up', 'marketing')",
            name="ck_consent_record_purpose",
        ),
        CheckConstraint(
            "action IN ('grant', 'revoke')",
            name="ck_consent_record_action",
        ),
        CheckConstraint(
            "char_length(btrim(policy_version)) > 0",
            name="ck_consent_record_policy_version",
        ),
        CheckConstraint(
            "char_length(btrim(channel)) > 0",
            name="ck_consent_record_channel",
        ),
        CheckConstraint(
            "target_channel IS NULL OR target_channel ~ '^[a-z][a-z0-9_-]{0,39}$'",
            name="ck_consent_record_target_channel",
        ),
        CheckConstraint(
            "char_length(btrim(locale)) > 0",
            name="ck_consent_record_locale",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_consent_record_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_consent_record_idempotency",
        ),
        CheckConstraint(
            "char_length(command_hash) = 64",
            name="ck_consent_record_command_hash",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > occurred_at",
            name="ck_consent_record_expiration",
        ),
        CheckConstraint(
            "action != 'revoke' OR expires_at IS NULL",
            name="ck_consent_record_revoke_expiration",
        ),
        CheckConstraint(
            "contact_point_id IS NULL OR contact_id IS NOT NULL",
            name="ck_consent_record_point_requires_contact",
        ),
        UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_consent_record_agent_idempotency",
        ),
        Index(
            "ix_consent_record_effective",
            "agent_id",
            "principal_id",
            "purpose",
            "contact_point_id",
            "occurred_at",
        ),
        Index(
            "ix_consent_record_target_effective",
            "agent_id",
            "principal_id",
            "purpose",
            "source_conversation_id",
            "target_channel",
            "contact_point_id",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_point_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_points.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    target_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
