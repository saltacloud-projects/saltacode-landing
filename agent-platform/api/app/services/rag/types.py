"""Tipos internos del pipeline RAG."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID


@dataclass(slots=True)
class StoredFile:
    sha256: str
    storage_key: str
    size_bytes: int
    mime_type: str
    extension: str
    path: Path
    duplicate: bool = False


@dataclass(slots=True)
class ExtractedPart:
    text: str
    page_number: int | None = None
    location_label: str | None = None
    section_title: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedDocument:
    parts: list[ExtractedPart]
    page_count: int
    parser_name: str
    parser_version: str
    extraction_method: str


@dataclass(slots=True)
class ChunkDraft:
    ordinal: int
    content: str
    token_count: int
    page_number: int | None
    location_label: str | None
    section_title: str | None
    metadata: dict


@dataclass(slots=True)
class RagHit:
    chunk_id: UUID
    document_id: UUID
    reference_code: str
    title: str
    version_number: int
    content: str
    page_number: int | None
    location_label: str | None
    section_title: str | None
    score: float
