"""Quote requests and immutable authoritative versions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel

_SHA256_HEX_SQL = "'^[0-9a-f]{64}$'"


class QuoteRequest(TimestampedModel):
    """Provider-neutral request that cannot manufacture a commercial price."""

    __tablename__ = "quote_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unavailable', 'review_required', 'issued', 'cancelled')",
            name="ck_quote_request_status",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_quote_request_state_version",
        ),
        CheckConstraint(
            "jsonb_typeof(requirements_json) = 'object'",
            name="ck_quote_request_requirements_object",
        ),
        CheckConstraint(
            "status NOT IN ('unavailable', 'review_required') OR "
            "failure_code IS NOT NULL",
            name="ck_quote_request_failure_reason",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_quote_request_command_hash",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_quote_request_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_quote_request_idempotency",
        ),
        UniqueConstraint(
            "opportunity_id",
            "idempotency_key",
            name="uq_quote_request_idempotency",
        ),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="unavailable",
        server_default="unavailable",
        nullable=False,
    )
    state_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    requirements_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QuoteVersion(Base):
    """Immutable issued version backed by authoritative external evidence."""

    __tablename__ = "quote_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_quote_version_number"),
        CheckConstraint("status = 'issued'", name="ck_quote_version_status"),
        CheckConstraint(
            "char_length(btrim(authority_name)) > 0 AND "
            "char_length(btrim(authority_version)) > 0 AND "
            "char_length(btrim(external_reference)) > 0 AND "
            "issued_at IS NOT NULL",
            name="ck_quote_version_authority_evidence",
        ),
        CheckConstraint(
            f"content_hash ~ {_SHA256_HEX_SQL}",
            name="ck_quote_version_content_hash",
        ),
        CheckConstraint(
            f"command_hash ~ {_SHA256_HEX_SQL}",
            name="ck_quote_version_command_hash",
        ),
        CheckConstraint(
            "issued_at <= created_at",
            name="ck_quote_version_issued_before_recorded",
        ),
        CheckConstraint(
            "char_length(btrim(correlation_id)) > 0",
            name="ck_quote_version_correlation",
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0",
            name="ck_quote_version_idempotency",
        ),
        UniqueConstraint(
            "quote_request_id",
            "version",
            name="uq_quote_version_request_version",
        ),
        UniqueConstraint(
            "quote_request_id",
            "idempotency_key",
            name="uq_quote_version_request_idempotency",
        ),
        UniqueConstraint(
            "authority_name",
            "external_reference",
            name="uq_quote_version_authority_reference",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    quote_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quote_requests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    authority_name: Mapped[str] = mapped_column(String(120), nullable=False)
    authority_version: Mapped[str] = mapped_column(String(80), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
