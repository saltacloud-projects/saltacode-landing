"""Chunking determinístico y completamente local que conserva ubicación."""

import math
import re

from app.services.rag.types import ChunkDraft, ExtractedDocument

_UNIT_RE = re.compile(r"\S+\s*", re.UNICODE)


def _estimated_tokens(value: str) -> int:
    # Estimación conservadora suficiente para ventanas de 800 frente al límite
    # de 8191 del modelo de embeddings. Evita descargas de vocabulario en runtime.
    return max(1, math.ceil(len(value.encode("utf-8")) / 3.5))


def build_chunks(
    document: ExtractedDocument,
    *,
    chunk_tokens: int,
    overlap_tokens: int,
) -> list[ChunkDraft]:
    if chunk_tokens < 100:
        raise ValueError("chunk_tokens debe ser al menos 100")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("chunk_overlap_tokens debe ser menor que chunk_tokens")

    chunks: list[ChunkDraft] = []
    ordinal = 0
    for part in document.parts:
        clean = "\n".join(
            line.strip() for line in part.text.splitlines() if line.strip()
        ).strip()
        if not clean:
            continue
        units: list[str] = []
        max_unit_chars = max(16, int(chunk_tokens * 0.75))
        for unit in _UNIT_RE.findall(clean):
            if _estimated_tokens(unit) <= chunk_tokens:
                units.append(unit)
            else:
                units.extend(
                    unit[index : index + max_unit_chars]
                    for index in range(0, len(unit), max_unit_chars)
                )
        start = 0
        while start < len(units):
            end = start
            token_count = 0
            while end < len(units):
                candidate_tokens = _estimated_tokens(units[end])
                if end > start and token_count + candidate_tokens > chunk_tokens:
                    break
                token_count += candidate_tokens
                end += 1
            content = "".join(units[start:end]).strip()
            if not content:
                break
            chunks.append(
                ChunkDraft(
                    ordinal=ordinal,
                    content=content,
                    token_count=_estimated_tokens(content),
                    page_number=part.page_number,
                    location_label=part.location_label,
                    section_title=part.section_title,
                    metadata=dict(part.metadata),
                )
            )
            ordinal += 1
            if end >= len(units):
                break
            overlap = 0
            next_start = end
            while next_start > start and overlap < overlap_tokens:
                next_start -= 1
                overlap += _estimated_tokens(units[next_start])
            start = max(start + 1, next_start)
    return chunks
