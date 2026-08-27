"""Worker durable de ingesta RAG basado en jobs PostgreSQL."""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.rag import (
    Document,
    DocumentBlob,
    DocumentChunk,
    DocumentEvent,
    DocumentFolder,
    DocumentIngestionJob,
    DocumentVersion,
    RagSettings,
)
from app.services.rag.chunking import build_chunks
from app.services.rag.embeddings import embedding_service
from app.services.rag.extraction import extract_document
from app.services.rag.settings import rag_settings_service
from app.services.rag.storage import document_storage

logger = logging.getLogger(__name__)


class RagIngestionWorker:
    def __init__(self) -> None:
        self._last_purge_monotonic = 0.0
        self._last_heartbeat_monotonic = 0.0

    async def run_forever(self) -> None:
        document_storage.ensure_ready_sync()
        logger.info("rag_worker_started", extra={"worker_id": settings.rag_worker_id})
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(settings.rag_worker_poll_seconds)

    async def run_once(self) -> bool:
        await self._heartbeat_if_due()
        await self._run_maintenance_if_due()
        async with AsyncSessionLocal() as db:
            job = await self._claim_job(db)
            if job is None:
                return False
            job_id = job.id
        await self._process_job(job_id)
        return True

    async def _heartbeat_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat_monotonic < 30:
            return
        async with AsyncSessionLocal() as db:
            async with db.begin():
                await db.execute(
                    update(RagSettings)
                    .where(RagSettings.key == "default")
                    .values(
                        worker_id=settings.rag_worker_id,
                        worker_last_heartbeat=datetime.now(timezone.utc),
                    )
                )
        self._last_heartbeat_monotonic = now

    async def _run_maintenance_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_purge_monotonic < 3600:
            return
        self._last_purge_monotonic = now
        try:
            await self._purge_expired_documents()
        except Exception as exc:
            logger.error("rag_purge_failed", extra={"error_type": type(exc).__name__})

    async def _purge_expired_documents(self) -> None:
        """Purga en lotes pequeños y elimina blobs sólo cuando ya no tienen referencias."""
        if document_storage.path_for(".backup-in-progress").exists():
            logger.info("rag_purge_skipped", extra={"reason": "backup_in_progress"})
            return
        storage_keys: list[str] = []
        purged = 0
        async with AsyncSessionLocal() as db:
            async with db.begin():
                documents = list(
                    (
                        await db.execute(
                            select(Document)
                            .where(
                                Document.deleted_at.is_not(None),
                                Document.purge_after <= datetime.now(timezone.utc),
                            )
                            .order_by(Document.purge_after)
                            .with_for_update(skip_locked=True)
                            .limit(100)
                        )
                    )
                    .scalars()
                    .all()
                )
                blob_ids = (
                    set(
                        (
                            await db.execute(
                                select(DocumentVersion.blob_id).where(
                                    DocumentVersion.document_id.in_(
                                        [item.id for item in documents]
                                    )
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if documents
                    else set()
                )
                for document in documents:
                    await db.delete(document)
                    purged += 1
                await db.flush()
                for blob_id in blob_ids:
                    references = (
                        await db.execute(
                            select(func.count())
                            .select_from(DocumentVersion)
                            .where(DocumentVersion.blob_id == blob_id)
                        )
                    ).scalar_one()
                    if references == 0:
                        blob = (
                            await db.execute(
                                select(DocumentBlob).where(DocumentBlob.id == blob_id)
                            )
                        ).scalar_one_or_none()
                        if blob is not None:
                            storage_keys.append(blob.storage_key)
                            await db.delete(blob)
        for storage_key in storage_keys:
            document_storage.delete(storage_key)
        async with AsyncSessionLocal() as db:
            known_keys = set(
                (await db.execute(select(DocumentBlob.storage_key))).scalars().all()
            )
        orphaned, stale_staging = document_storage.cleanup_orphans(known_keys)
        if purged or orphaned or stale_staging:
            logger.info(
                "rag_storage_maintenance",
                extra={
                    "documents_purged": purged,
                    "blobs_purged": len(storage_keys),
                    "orphaned_blobs": orphaned,
                    "stale_staging": stale_staging,
                },
            )

    async def _claim_job(self, db: AsyncSession) -> DocumentIngestionJob | None:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(minutes=30)
        async with db.begin():
            result = await db.execute(
                select(DocumentIngestionJob)
                .where(
                    or_(
                        DocumentIngestionJob.status == "queued",
                        (
                            (DocumentIngestionJob.status == "processing")
                            & (DocumentIngestionJob.locked_at < stale_before)
                        ),
                    ),
                    or_(
                        DocumentIngestionJob.next_attempt_at.is_(None),
                        DocumentIngestionJob.next_attempt_at <= now,
                    ),
                )
                .order_by(DocumentIngestionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "processing"
            job.stage = "starting"
            job.progress_percent = 1
            job.attempts += 1
            job.locked_by = settings.rag_worker_id
            job.locked_at = now
            job.error_code = None
            job.error_message = None
            await db.flush()
            return job

    async def _process_job(self, job_id: uuid.UUID) -> None:
        request_id = str(job_id)
        try:
            async with AsyncSessionLocal() as db:
                job, version, blob, document, folder = await self._load_context(
                    db, job_id
                )
                rag_settings = await rag_settings_service.require(db)
                path = document_storage.path_for(blob.storage_key)
                if not path.is_file():
                    raise RuntimeError(
                        "El archivo original no existe en almacenamiento"
                    )
                await self._progress(db, job, "extracting", 10)
                extracted = await extract_document(
                    path,
                    extension=blob.extension,
                    ocr_enabled=rag_settings.ocr_enabled,
                    vision_model=rag_settings.vision_model,
                    request_id=request_id,
                )
                chunks = build_chunks(
                    extracted,
                    chunk_tokens=rag_settings.chunk_tokens,
                    overlap_tokens=rag_settings.chunk_overlap_tokens,
                )
                if not chunks:
                    raise RuntimeError("La extracción no generó chunks útiles")
                await self._progress(db, job, "embedding", 45)
                embeddings = await embedding_service.embed_texts(
                    [chunk.content for chunk in chunks],
                    model=rag_settings.embedding_model,
                    dimensions=rag_settings.embedding_dimensions,
                    request_id=request_id,
                )
                await self._persist_success(
                    db=db,
                    job=job,
                    version=version,
                    document=document,
                    folder=folder,
                    extracted=extracted,
                    chunks=chunks,
                    embeddings=embeddings,
                    embedding_model=rag_settings.embedding_model,
                    embedding_dimensions=rag_settings.embedding_dimensions,
                )
        except Exception as exc:
            logger.error(
                "rag_ingestion_failed",
                extra={"job_id": str(job_id), "error_type": type(exc).__name__},
            )
            await self._persist_failure(job_id, exc)

    async def _load_context(self, db: AsyncSession, job_id: uuid.UUID):
        row = (
            await db.execute(
                select(
                    DocumentIngestionJob,
                    DocumentVersion,
                    DocumentBlob,
                    Document,
                    DocumentFolder,
                )
                .join(
                    DocumentVersion,
                    DocumentVersion.id == DocumentIngestionJob.version_id,
                )
                .join(DocumentBlob, DocumentBlob.id == DocumentVersion.blob_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .join(DocumentFolder, DocumentFolder.id == Document.folder_id)
                .where(DocumentIngestionJob.id == job_id)
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("Job de ingesta inexistente")
        return row

    async def _progress(
        self,
        db: AsyncSession,
        job: DocumentIngestionJob,
        stage: str,
        percent: int,
    ) -> None:
        job.stage = stage
        job.progress_percent = percent
        job.locked_at = datetime.now(timezone.utc)
        await db.commit()

    async def _persist_success(
        self,
        *,
        db: AsyncSession,
        job: DocumentIngestionJob,
        version: DocumentVersion,
        document: Document,
        folder: DocumentFolder,
        extracted,
        chunks,
        embeddings,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with db.begin():
            await db.execute(
                delete(DocumentChunk).where(DocumentChunk.version_id == version.id)
            )
            await db.execute(
                update(DocumentChunk)
                .where(
                    DocumentChunk.version_id.in_(
                        select(DocumentVersion.id).where(
                            DocumentVersion.document_id == document.id
                        )
                    )
                )
                .values(is_retrievable=False)
            )
            await db.execute(
                update(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .values(is_current=False)
            )
            retrievable = document.deleted_at is None
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                db.add(
                    DocumentChunk(
                        version_id=version.id,
                        area_id=folder.area_id,
                        ordinal=chunk.ordinal,
                        content=chunk.content,
                        page_number=chunk.page_number,
                        location_label=chunk.location_label,
                        section_title=chunk.section_title,
                        token_count=chunk.token_count,
                        chunk_metadata=chunk.metadata,
                        embedding=embedding,
                        is_retrievable=retrievable,
                    )
                )
            version.status = "ready"
            version.is_current = True
            version.parser_name = extracted.parser_name
            version.parser_version = extracted.parser_version
            version.extraction_method = extracted.extraction_method
            version.embedding_model = embedding_model
            version.embedding_dimensions = embedding_dimensions
            version.page_count = extracted.page_count
            version.chunk_count = len(chunks)
            version.error_code = None
            version.error_message = None
            version.published_at = now
            document.status = "published" if retrievable else "deleted"
            job.status = "completed"
            job.stage = "completed"
            job.progress_percent = 100
            job.completed_at = now
            job.locked_at = None
            job.next_attempt_at = None
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    version_id=version.id,
                    event_type="published",
                    event_metadata={
                        "chunks": len(chunks),
                        "method": extracted.extraction_method,
                    },
                )
            )
        logger.info(
            "rag_ingestion_completed",
            extra={
                "job_id": str(job.id),
                "document_id": str(document.id),
                "chunks": len(chunks),
            },
        )

    async def _persist_failure(self, job_id: uuid.UUID, exc: Exception) -> None:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                row = (
                    await db.execute(
                        select(DocumentIngestionJob, DocumentVersion, Document)
                        .join(
                            DocumentVersion,
                            DocumentVersion.id == DocumentIngestionJob.version_id,
                        )
                        .join(Document, Document.id == DocumentVersion.document_id)
                        .where(DocumentIngestionJob.id == job_id)
                        .with_for_update()
                    )
                ).one_or_none()
                if row is None:
                    return
                job, version, document = row
                message = str(exc)[:1000] or type(exc).__name__
                job.error_code = type(exc).__name__[:80]
                job.error_message = message
                job.locked_at = None
                if job.attempts < job.max_attempts:
                    job.status = "queued"
                    job.stage = "retry_wait"
                    job.progress_percent = 0
                    job.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                        minutes=2**job.attempts
                    )
                    version.status = "queued"
                else:
                    job.status = "failed"
                    job.stage = "failed"
                    job.completed_at = datetime.now(timezone.utc)
                    version.status = "failed"
                    version.error_code = job.error_code
                    version.error_message = message
                    has_current = (
                        await db.execute(
                            select(func.count())
                            .select_from(DocumentVersion)
                            .where(
                                DocumentVersion.document_id == document.id,
                                DocumentVersion.is_current == True,  # noqa: E712
                            )
                        )
                    ).scalar_one() > 0
                    if not has_current and document.deleted_at is None:
                        document.status = "failed"
                    db.add(
                        DocumentEvent(
                            document_id=document.id,
                            version_id=version.id,
                            event_type="ingestion_failed",
                            event_metadata={"error_code": job.error_code},
                        )
                    )


rag_ingestion_worker = RagIngestionWorker()
