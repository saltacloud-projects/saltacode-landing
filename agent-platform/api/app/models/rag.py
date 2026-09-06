"""Modelos persistentes de áreas, documentos e ingesta RAG."""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class OrganizationArea(TimestampedModel):
    __tablename__ = "organization_areas"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_general: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )


class AuthorizedUserArea(TimestampedModel):
    __tablename__ = "authorized_user_areas"
    __table_args__ = (
        UniqueConstraint("user_id", "area_id", name="uq_authorized_user_area"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("authorized_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_areas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class DocumentFolder(TimestampedModel):
    __tablename__ = "document_folders"
    __table_args__ = (
        UniqueConstraint(
            "area_id", "parent_id", "normalized_name", name="uq_document_folder_sibling"
        ),
        Index(
            "uq_document_folder_root",
            "area_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )

    area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_areas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class DocumentBlob(TimestampedModel):
    __tablename__ = "document_blobs"

    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)


class Document(TimestampedModel):
    __tablename__ = "documents"

    reference_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    internal_code: Mapped[str | None] = mapped_column(String(100), index=True)
    responsible: Mapped[str | None] = mapped_column(String(160))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(30), default="processing", nullable=False, index=True
    )
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class DocumentVersion(TimestampedModel):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_version_number"
        ),
        Index(
            "uq_document_version_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blob_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_blobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default="queued", nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parser_name: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(40))
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(TimestampedModel):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_document_chunk_ordinal"),
        Index("ix_document_chunks_retrievable_area", "area_id", "is_retrievable"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("is_retrievable"),
        ),
        Index(
            "ix_document_chunks_search_vector", "search_vector", postgresql_using="gin"
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_areas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    location_label: Mapped[str | None] = mapped_column(String(160))
    section_title: Mapped[str | None] = mapped_column(String(300))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, coalesce(content, ''))", persisted=True
        ),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    is_retrievable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )


class DocumentIngestionJob(TimestampedModel):
    __tablename__ = "document_ingestion_jobs"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default="queued", nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagSettings(TimestampedModel):
    __tablename__ = "rag_settings"

    key: Mapped[str] = mapped_column(
        String(40), unique=True, default="default", nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(100), default="text-embedding-3-small", nullable=False
    )
    embedding_dimensions: Mapped[int] = mapped_column(
        Integer, default=1536, nullable=False
    )
    vision_model: Mapped[str] = mapped_column(
        String(100), default="gpt-4.1-mini", nullable=False
    )
    max_file_bytes: Mapped[int] = mapped_column(
        BigInteger, default=104857600, nullable=False
    )
    max_batch_bytes: Mapped[int] = mapped_column(
        BigInteger, default=2147483648, nullable=False
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    chunk_tokens: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    chunk_overlap_tokens: Mapped[int] = mapped_column(
        Integer, default=120, nullable=False
    )
    retrieval_top_k: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    min_relevance_score: Mapped[float] = mapped_column(
        Float, default=0.35, nullable=False
    )
    vector_weight: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    lexical_weight: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    worker_last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class DocumentEvent(TimestampedModel):
    __tablename__ = "document_events"

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
