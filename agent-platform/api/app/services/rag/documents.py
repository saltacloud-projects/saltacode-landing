"""Operaciones de dominio para áreas, carpetas, versiones y uploads."""

import logging
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.models.admin_user import AdminUser
from app.models.rag import (
    Document,
    DocumentBlob,
    DocumentChunk,
    DocumentEvent,
    DocumentFolder,
    DocumentIngestionJob,
    DocumentVersion,
    OrganizationArea,
)
from app.services.rag.settings import rag_settings_service
from app.services.rag.storage import document_storage

logger = logging.getLogger(__name__)


class DocumentDomainError(ValueError):
    pass


def normalize_folder_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


class RagDocumentService:
    async def ensure_folder_path(
        self,
        db: AsyncSession,
        *,
        area_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        relative_path: str | None,
    ) -> DocumentFolder:
        area = (
            await db.execute(
                select(OrganizationArea)
                .where(
                    OrganizationArea.id == area_id,
                    OrganizationArea.is_active == True,  # noqa: E712
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if area is None:
            raise DocumentDomainError("Área inexistente o inactiva")

        parent = None
        if parent_id is not None:
            parent = (
                await db.execute(
                    select(DocumentFolder).where(DocumentFolder.id == parent_id)
                )
            ).scalar_one_or_none()
            if parent is None or parent.area_id != area_id:
                raise DocumentDomainError("Carpeta base inválida para el área")

        raw_segments = (relative_path or "").replace("\\", "/").split("/")
        if any(segment.strip() in {".", ".."} for segment in raw_segments):
            raise DocumentDomainError("La ruta de carpeta contiene segmentos inválidos")
        segments = [segment.strip() for segment in raw_segments if segment.strip()]
        if not segments and parent is not None:
            return parent
        if not segments:
            segments = [area.name]

        current_parent_id = parent.id if parent else None
        current: DocumentFolder | None = parent
        for segment in segments:
            if len(segment) > 255:
                raise DocumentDomainError("Un nombre de carpeta supera 255 caracteres")
            normalized = normalize_folder_name(segment)
            if not normalized or any(ord(char) < 32 for char in segment):
                raise DocumentDomainError("Un nombre de carpeta es inválido")
            query = select(DocumentFolder).where(
                DocumentFolder.area_id == area_id,
                DocumentFolder.normalized_name == normalized,
            )
            if current_parent_id is None:
                query = query.where(DocumentFolder.parent_id.is_(None))
            else:
                query = query.where(DocumentFolder.parent_id == current_parent_id)
            current = (await db.execute(query)).scalar_one_or_none()
            if current is None:
                current = DocumentFolder(
                    area_id=area_id,
                    parent_id=current_parent_id,
                    name=segment,
                    normalized_name=normalized,
                )
                db.add(current)
                await db.flush()
            current_parent_id = current.id
        if current is None:
            raise DocumentDomainError("No se pudo resolver la carpeta")
        return current

    async def queue_upload(
        self,
        db: AsyncSession,
        *,
        upload: UploadFile,
        folder: DocumentFolder,
        admin: AdminUser,
        batch_id: uuid.UUID,
        document_id: uuid.UUID | None = None,
        title: str | None = None,
        allow_archive: bool = False,
    ) -> tuple[Document, DocumentVersion, DocumentIngestionJob, bool]:
        rag_settings = await rag_settings_service.require(db)
        stored = await document_storage.save_upload(
            upload,
            max_bytes=rag_settings.max_batch_bytes
            if allow_archive
            else rag_settings.max_file_bytes,
            allow_archive=allow_archive,
        )
        inserted_blob_id = (
            await db.execute(
                pg_insert(DocumentBlob)
                .values(
                    id=uuid.uuid4(),
                    sha256=stored.sha256,
                    storage_key=stored.storage_key,
                    size_bytes=stored.size_bytes,
                    mime_type=stored.mime_type,
                    extension=stored.extension,
                )
                .on_conflict_do_nothing(index_elements=[DocumentBlob.sha256])
                .returning(DocumentBlob.id)
            )
        ).scalar_one_or_none()
        blob = (
            await db.execute(
                select(DocumentBlob).where(DocumentBlob.sha256 == stored.sha256)
            )
        ).scalar_one()
        duplicate = stored.duplicate or inserted_blob_id is None

        if document_id is None:
            doc_uuid = uuid.uuid4()
            safe_stem = Path(
                (upload.filename or "Documento").replace("\\", "/")
            ).stem.strip()
            document = Document(
                id=doc_uuid,
                reference_code=f"DOC-{doc_uuid.hex[:8].upper()}",
                folder_id=folder.id,
                title=(title or safe_stem or "Documento")[:300],
                status="processing",
                created_by_admin_id=admin.id,
            )
            db.add(document)
            version_number = 1
        else:
            document = (
                await db.execute(
                    select(Document)
                    .where(
                        Document.id == document_id,
                        Document.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if document is None:
                raise DocumentDomainError("Documento no encontrado")
            version_number = (
                await db.execute(
                    select(
                        func.coalesce(func.max(DocumentVersion.version_number), 0)
                    ).where(DocumentVersion.document_id == document.id)
                )
            ).scalar_one() + 1
        await db.flush()

        safe_filename = Path((upload.filename or "").replace("\\", "/")).name
        version = DocumentVersion(
            document_id=document.id,
            blob_id=blob.id,
            version_number=version_number,
            status="queued",
            original_filename=(
                safe_filename or f"{document.reference_code}.{stored.extension}"
            )[:500],
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
        )
        db.add(version)
        await db.flush()
        job = DocumentIngestionJob(
            version_id=version.id,
            batch_id=batch_id,
            status="queued",
            stage="queued",
        )
        db.add(job)
        db.add(
            DocumentEvent(
                document_id=document.id,
                version_id=version.id,
                actor_admin_id=admin.id,
                event_type="upload_queued",
                event_metadata={"duplicate_hash": duplicate, "batch_id": str(batch_id)},
            )
        )
        await db.flush()
        logger.info(
            "rag_upload_queued",
            extra={
                "document_id": str(document.id),
                "version_id": str(version.id),
                "batch_id": str(batch_id),
                "duplicate_hash": duplicate,
            },
        )
        return document, version, job, duplicate

    async def soft_delete(
        self,
        db: AsyncSession,
        *,
        document: Document,
        actor_admin_id: uuid.UUID,
    ) -> None:
        settings_row = await rag_settings_service.require(db)
        now = datetime.now(timezone.utc)
        document.status = "deleted"
        document.deleted_at = now
        document.purge_after = now + timedelta(days=settings_row.retention_days)
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
        db.add(
            DocumentEvent(
                document_id=document.id,
                actor_admin_id=actor_admin_id,
                event_type="deleted",
                event_metadata={"purge_after": document.purge_after.isoformat()},
            )
        )

    async def restore(
        self,
        db: AsyncSession,
        *,
        document: Document,
        actor_admin_id: uuid.UUID,
    ) -> None:
        if document.deleted_at is None:
            return
        document.deleted_at = None
        document.purge_after = None
        current = (
            await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.is_current == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        document.status = "published" if current else "failed"
        if current is not None:
            await db.execute(
                update(DocumentChunk)
                .where(DocumentChunk.version_id == current.id)
                .values(is_retrievable=True)
            )
        db.add(
            DocumentEvent(
                document_id=document.id,
                actor_admin_id=actor_admin_id,
                event_type="restored",
                event_metadata={},
            )
        )

    async def queue_reindex(
        self,
        db: AsyncSession,
        *,
        document: Document,
        actor_admin_id: uuid.UUID,
    ) -> tuple[DocumentVersion, DocumentIngestionJob]:
        """Crea una versión derivada del original vigente sin sobrescribirlo."""
        current = (
            await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.is_current == True,  # noqa: E712
                    DocumentVersion.status == "ready",
                )
            )
        ).scalar_one_or_none()
        if current is None:
            raise DocumentDomainError(
                "El documento no tiene una versión vigente reindexable"
            )
        version_number = (
            await db.execute(
                select(
                    func.coalesce(func.max(DocumentVersion.version_number), 0)
                ).where(DocumentVersion.document_id == document.id)
            )
        ).scalar_one() + 1
        version = DocumentVersion(
            document_id=document.id,
            blob_id=current.blob_id,
            version_number=version_number,
            status="queued",
            original_filename=current.original_filename,
            mime_type=current.mime_type,
            size_bytes=current.size_bytes,
        )
        db.add(version)
        await db.flush()
        job = DocumentIngestionJob(
            version_id=version.id,
            batch_id=uuid.uuid4(),
            status="queued",
            stage="queued",
        )
        db.add(job)
        db.add(
            DocumentEvent(
                document_id=document.id,
                version_id=version.id,
                actor_admin_id=actor_admin_id,
                event_type="reindex_queued",
                event_metadata={"source_version_id": str(current.id)},
            )
        )
        await db.flush()
        return version, job


rag_document_service = RagDocumentService()
