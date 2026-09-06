"""Contratos del panel para la administración documental RAG."""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class AreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(
        min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    description: str | None = None


class AreaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class AreaOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    is_general: bool
    is_active: bool
    folder_count: int = 0
    document_count: int = 0


class FolderCreate(BaseModel):
    area_id: str
    parent_id: str | None = None
    name: str = Field(min_length=1, max_length=255)


class FolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class FolderOut(BaseModel):
    id: str
    area_id: str
    parent_id: str | None
    name: str
    document_count: int = 0


class DocumentUpdate(BaseModel):
    folder_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    internal_code: str | None = Field(default=None, max_length=100)
    responsible: str | None = Field(default=None, max_length=160)
    effective_from: date | None = None
    effective_to: date | None = None

    @model_validator(mode="after")
    def validate_effective_dates(self):
        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            raise ValueError(
                "La vigencia hasta no puede ser anterior a la vigencia desde"
            )
        return self


class VersionOut(BaseModel):
    id: str
    version_number: int
    is_current: bool
    status: str
    original_filename: str
    mime_type: str
    size_bytes: int
    parser_name: str | None
    extraction_method: str | None
    page_count: int
    chunk_count: int
    error_code: str | None
    error_message: str | None
    published_at: datetime | None
    created_at: datetime


class JobOut(BaseModel):
    id: str
    batch_id: str
    status: str
    stage: str
    progress_percent: int
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    completed_at: datetime | None


class DocumentOut(BaseModel):
    id: str
    reference_code: str
    folder_id: str
    folder_name: str
    area_id: str
    area_name: str
    title: str
    description: str | None
    internal_code: str | None
    responsible: str | None
    effective_from: date | None
    effective_to: date | None
    status: str
    deleted_at: datetime | None
    purge_after: datetime | None
    current_version: VersionOut | None
    current_job: JobOut | None
    created_at: datetime
    updated_at: datetime


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class UploadItemOut(BaseModel):
    document_id: str
    reference_code: str
    version_id: str
    job_id: str
    filename: str
    duplicate_hash: bool


class UploadBatchOut(BaseModel):
    batch_id: str
    accepted: list[UploadItemOut]
    rejected: list[dict[str, str]] = Field(default_factory=list)


class RagStatsOut(BaseModel):
    documents_total: int
    published: int
    processing: int
    failed: int
    deleted: int
    chunks: int
    storage_bytes: int
    queue_depth: int
    worker_last_activity: datetime | None


class RagSettingsUpdate(BaseModel):
    enabled: bool | None = None
    max_file_bytes: int | None = Field(default=None, ge=1_048_576, le=1_073_741_824)
    max_batch_bytes: int | None = Field(default=None, ge=1_048_576, le=10_737_418_240)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    chunk_tokens: int | None = Field(default=None, ge=200, le=4000)
    chunk_overlap_tokens: int | None = Field(default=None, ge=0, le=1000)
    retrieval_top_k: int | None = Field(default=None, ge=1, le=30)
    min_relevance_score: float | None = Field(default=None, ge=0, le=1)
    vector_weight: float | None = Field(default=None, ge=0, le=1)
    lexical_weight: float | None = Field(default=None, ge=0, le=1)
    ocr_enabled: bool | None = None


class RagSettingsOut(BaseModel):
    enabled: bool
    embedding_model: str
    embedding_dimensions: int
    vision_model: str
    max_file_bytes: int
    max_batch_bytes: int
    retention_days: int
    chunk_tokens: int
    chunk_overlap_tokens: int
    retrieval_top_k: int
    min_relevance_score: float
    vector_weight: float
    lexical_weight: float
    ocr_enabled: bool


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    user_id: str | None = None
    area_ids: list[str] = Field(default_factory=list)


class RagSearchHitOut(BaseModel):
    reference_code: str
    title: str
    version_number: int
    content: str
    page_number: int | None
    location_label: str | None
    section_title: str | None
    score: float
