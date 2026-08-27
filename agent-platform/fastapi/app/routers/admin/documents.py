"""Administración persistente de áreas, carpetas y documentos RAG."""

import stat
import uuid
import zipfile
from pathlib import PurePosixPath

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
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
    RagSettings,
)
from app.models.tool_config import ToolConfig
from app.routers.admin.auth import require_permission
from app.schemas.rag import (
    AreaCreate,
    AreaOut,
    AreaUpdate,
    DocumentListOut,
    DocumentOut,
    DocumentUpdate,
    FolderCreate,
    FolderOut,
    FolderUpdate,
    JobOut,
    RagSearchHitOut,
    RagSearchRequest,
    RagSettingsOut,
    RagSettingsUpdate,
    RagStatsOut,
    UploadBatchOut,
    UploadItemOut,
    VersionOut,
)
from app.services.admin_rbac import AdminPermission
from app.services.rag.documents import (
    DocumentDomainError,
    normalize_folder_name,
    rag_document_service,
)
from app.services.rag.retrieval import rag_retrieval_service
from app.services.rag.settings import rag_settings_service
from app.services.rag.storage import ALLOWED_EXTENSIONS, StorageError, document_storage

router = APIRouter(
    tags=["admin-documents"],
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_READ))],
)


def _uuid(value: str | None, label: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{label} inválido") from exc


def _version_out(version: DocumentVersion | None) -> VersionOut | None:
    if version is None:
        return None
    return VersionOut(
        id=str(version.id),
        version_number=version.version_number,
        is_current=version.is_current,
        status=version.status,
        original_filename=version.original_filename,
        mime_type=version.mime_type,
        size_bytes=version.size_bytes,
        parser_name=version.parser_name,
        extraction_method=version.extraction_method,
        page_count=version.page_count,
        chunk_count=version.chunk_count,
        error_code=version.error_code,
        error_message=version.error_message,
        published_at=version.published_at,
        created_at=version.created_at,
    )


def _job_out(job: DocumentIngestionJob | None) -> JobOut | None:
    if job is None:
        return None
    return JobOut(
        id=str(job.id),
        batch_id=str(job.batch_id),
        status=job.status,
        stage=job.stage,
        progress_percent=job.progress_percent,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        error_code=job.error_code,
        error_message=job.error_message,
        completed_at=job.completed_at,
    )


def _build_document_out(
    document: Document,
    folder: DocumentFolder,
    area: OrganizationArea,
    current: DocumentVersion | None,
    latest_job: DocumentIngestionJob | None,
) -> DocumentOut:
    return DocumentOut(
        id=str(document.id),
        reference_code=document.reference_code,
        folder_id=str(folder.id),
        folder_name=folder.name,
        area_id=str(area.id),
        area_name=area.name,
        title=document.title,
        description=document.description,
        internal_code=document.internal_code,
        responsible=document.responsible,
        effective_from=document.effective_from,
        effective_to=document.effective_to,
        status=document.status,
        deleted_at=document.deleted_at,
        purge_after=document.purge_after,
        current_version=_version_out(current),
        current_job=_job_out(latest_job),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _document_list_base(filters: list):
    """Consulta base con joins explícitos para listado, conteo y filtros."""
    return (
        select(Document, DocumentFolder, OrganizationArea)
        .select_from(Document)
        .join(DocumentFolder, DocumentFolder.id == Document.folder_id)
        .join(OrganizationArea, OrganizationArea.id == DocumentFolder.area_id)
        .where(*filters)
    )


async def _document_out(
    db: AsyncSession,
    document: Document,
    folder: DocumentFolder,
    area: OrganizationArea,
) -> DocumentOut:
    current = (
        await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.is_current == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    latest_job = (
        await db.execute(
            select(DocumentIngestionJob)
            .join(
                DocumentVersion, DocumentVersion.id == DocumentIngestionJob.version_id
            )
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentIngestionJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _build_document_out(document, folder, area, current, latest_job)


async def _get_document_row(
    db: AsyncSession, document_id: uuid.UUID, *, include_deleted: bool = True
):
    query = (
        select(Document, DocumentFolder, OrganizationArea)
        .join(DocumentFolder, DocumentFolder.id == Document.folder_id)
        .join(OrganizationArea, OrganizationArea.id == DocumentFolder.area_id)
        .where(Document.id == document_id)
    )
    if not include_deleted:
        query = query.where(Document.deleted_at.is_(None))
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return row


@router.get("/areas", response_model=list[AreaOut])
async def list_areas(db: AsyncSession = Depends(get_db)):
    areas = (
        (await db.execute(select(OrganizationArea).order_by(OrganizationArea.name)))
        .scalars()
        .all()
    )
    folder_counts = dict(
        (
            await db.execute(
                select(DocumentFolder.area_id, func.count(DocumentFolder.id)).group_by(
                    DocumentFolder.area_id
                )
            )
        ).all()
    )
    doc_counts = dict(
        (
            await db.execute(
                select(DocumentFolder.area_id, func.count(Document.id))
                .join(Document, Document.folder_id == DocumentFolder.id)
                .where(Document.deleted_at.is_(None))
                .group_by(DocumentFolder.area_id)
            )
        ).all()
    )
    return [
        AreaOut(
            id=str(area.id),
            name=area.name,
            slug=area.slug,
            description=area.description,
            is_general=area.is_general,
            is_active=area.is_active,
            folder_count=folder_counts.get(area.id, 0),
            document_count=doc_counts.get(area.id, 0),
        )
        for area in areas
    ]


@router.post(
    "/areas",
    response_model=AreaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def create_area(
    data: AreaCreate,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY)),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(
            select(OrganizationArea.id).where(OrganizationArea.slug == data.slug)
        )
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Ya existe un área con ese slug")
    area = OrganizationArea(
        name=data.name.strip(), slug=data.slug, description=data.description
    )
    db.add(area)
    await db.flush()
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="area_created",
            event_metadata={"area_id": str(area.id)},
        )
    )
    return AreaOut(
        id=str(area.id),
        name=area.name,
        slug=area.slug,
        description=area.description,
        is_general=False,
        is_active=True,
    )


@router.patch(
    "/areas/{area_id}",
    response_model=AreaOut,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def update_area(
    area_id: str,
    data: AreaUpdate,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY)),
    db: AsyncSession = Depends(get_db),
):
    uid = _uuid(area_id, "Área")
    area = (
        await db.execute(select(OrganizationArea).where(OrganizationArea.id == uid))
    ).scalar_one_or_none()
    if area is None:
        raise HTTPException(status_code=404, detail="Área no encontrada")
    payload = data.model_dump(exclude_unset=True)
    if area.is_general and payload.get("is_active") is False:
        raise HTTPException(
            status_code=409, detail="El área General no puede desactivarse"
        )
    for key, value in payload.items():
        setattr(area, key, value.strip() if key == "name" and value else value)
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="area_updated",
            event_metadata={"area_id": str(area.id), "fields": sorted(payload)},
        )
    )
    await db.flush()
    folder_count = (
        await db.execute(
            select(func.count())
            .select_from(DocumentFolder)
            .where(DocumentFolder.area_id == area.id)
        )
    ).scalar_one()
    document_count = (
        await db.execute(
            select(func.count())
            .select_from(Document)
            .join(DocumentFolder)
            .where(DocumentFolder.area_id == area.id, Document.deleted_at.is_(None))
        )
    ).scalar_one()
    return AreaOut(
        id=str(area.id),
        name=area.name,
        slug=area.slug,
        description=area.description,
        is_general=area.is_general,
        is_active=area.is_active,
        folder_count=folder_count,
        document_count=document_count,
    )


@router.delete(
    "/areas/{area_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def delete_area(
    area_id: str,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY)),
    db: AsyncSession = Depends(get_db),
):
    uid = _uuid(area_id, "Área")
    area = (
        await db.execute(select(OrganizationArea).where(OrganizationArea.id == uid))
    ).scalar_one_or_none()
    if area is None:
        raise HTTPException(status_code=404, detail="Área no encontrada")
    if area.is_general:
        raise HTTPException(
            status_code=409, detail="El área General no puede eliminarse"
        )
    has_folders = (
        await db.execute(
            select(func.count())
            .select_from(DocumentFolder)
            .where(DocumentFolder.area_id == area.id)
        )
    ).scalar_one()
    if has_folders:
        raise HTTPException(
            status_code=409,
            detail="El área contiene carpetas; vacíela antes de eliminarla",
        )
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="area_deleted",
            event_metadata={"area_id": str(area.id)},
        )
    )
    await db.delete(area)


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(area_id: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(DocumentFolder).order_by(
        DocumentFolder.sort_order, DocumentFolder.name
    )
    if area_id:
        query = query.where(DocumentFolder.area_id == _uuid(area_id, "Área"))
    folders = (await db.execute(query)).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(Document.folder_id, func.count(Document.id))
                .where(Document.deleted_at.is_(None))
                .group_by(Document.folder_id)
            )
        ).all()
    )
    return [
        FolderOut(
            id=str(folder.id),
            area_id=str(folder.area_id),
            parent_id=str(folder.parent_id) if folder.parent_id else None,
            name=folder.name,
            document_count=counts.get(folder.id, 0),
        )
        for folder in folders
    ]


@router.post(
    "/folders",
    response_model=FolderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def create_folder(
    data: FolderCreate,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY)),
    db: AsyncSession = Depends(get_db),
):
    try:
        folder = await rag_document_service.ensure_folder_path(
            db,
            area_id=_uuid(data.area_id, "Área"),
            parent_id=_uuid(data.parent_id, "Carpeta padre"),
            relative_path=data.name,
        )
    except DocumentDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="folder_created",
            event_metadata={
                "folder_id": str(folder.id),
                "area_id": str(folder.area_id),
            },
        )
    )
    return FolderOut(
        id=str(folder.id),
        area_id=str(folder.area_id),
        parent_id=str(folder.parent_id) if folder.parent_id else None,
        name=folder.name,
    )


@router.patch(
    "/folders/{folder_id}",
    response_model=FolderOut,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def update_folder(
    folder_id: str,
    data: FolderUpdate,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY)),
    db: AsyncSession = Depends(get_db),
):
    uid = _uuid(folder_id, "Carpeta")
    folder = (
        await db.execute(select(DocumentFolder).where(DocumentFolder.id == uid))
    ).scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    normalized = normalize_folder_name(data.name)
    duplicate = (
        await db.execute(
            select(DocumentFolder.id).where(
                DocumentFolder.area_id == folder.area_id,
                DocumentFolder.parent_id == folder.parent_id,
                DocumentFolder.normalized_name == normalized,
                DocumentFolder.id != folder.id,
            )
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409, detail="Ya existe una carpeta con ese nombre"
        )
    folder.name = data.name.strip()
    folder.normalized_name = normalized
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="folder_updated",
            event_metadata={"folder_id": str(folder.id)},
        )
    )
    count = (
        await db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.folder_id == folder.id, Document.deleted_at.is_(None))
        )
    ).scalar_one()
    return FolderOut(
        id=str(folder.id),
        area_id=str(folder.area_id),
        parent_id=str(folder.parent_id) if folder.parent_id else None,
        name=folder.name,
        document_count=count,
    )


@router.delete(
    "/folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def delete_folder(
    folder_id: str,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY)),
    db: AsyncSession = Depends(get_db),
):
    uid = _uuid(folder_id, "Carpeta")
    folder = (
        await db.execute(select(DocumentFolder).where(DocumentFolder.id == uid))
    ).scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    child_count = (
        await db.execute(
            select(func.count())
            .select_from(DocumentFolder)
            .where(DocumentFolder.parent_id == uid)
        )
    ).scalar_one()
    doc_count = (
        await db.execute(
            select(func.count()).select_from(Document).where(Document.folder_id == uid)
        )
    ).scalar_one()
    if child_count or doc_count:
        raise HTTPException(status_code=409, detail="La carpeta no está vacía")
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="folder_deleted",
            event_metadata={
                "folder_id": str(folder.id),
                "area_id": str(folder.area_id),
            },
        )
    )
    await db.delete(folder)


async def _queue_one(
    db: AsyncSession,
    *,
    upload: UploadFile,
    area_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    relative_path: str | None,
    admin: AdminUser,
    batch_id: uuid.UUID,
    title: str | None = None,
) -> UploadItemOut:
    folder = await rag_document_service.ensure_folder_path(
        db,
        area_id=area_id,
        parent_id=parent_id,
        relative_path=relative_path,
    )
    document, version, job, duplicate = await rag_document_service.queue_upload(
        db,
        upload=upload,
        folder=folder,
        admin=admin,
        batch_id=batch_id,
        title=title,
    )
    return UploadItemOut(
        document_id=str(document.id),
        reference_code=document.reference_code,
        version_id=str(version.id),
        job_id=str(job.id),
        filename=version.original_filename,
        duplicate_hash=duplicate,
    )


@router.post(
    "/upload",
    response_model=UploadBatchOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE))],
)
async def upload_documents(
    area_id: str = Form(...),
    folder_id: str | None = Form(None),
    relative_paths: list[str] = Form(default=[]),
    title: str | None = Form(None),
    files: list[UploadFile] = File(...),
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    area_uuid = _uuid(area_id, "Área")
    folder_uuid = _uuid(folder_id, "Carpeta")
    settings_row = await rag_settings_service.require(db)
    batch_id = uuid.uuid4()
    accepted: list[UploadItemOut] = []
    rejected: list[dict[str, str]] = []
    if len(files) > 10_000:
        raise HTTPException(status_code=413, detail="El lote supera 10.000 archivos")
    if sum(upload.size or 0 for upload in files) > settings_row.max_batch_bytes:
        raise HTTPException(
            status_code=413, detail="El lote supera el límite total configurado"
        )

    for index, upload in enumerate(files):
        filename = upload.filename or "archivo"
        extension = PurePosixPath(filename).suffix.lower().lstrip(".")
        base_path = relative_paths[index] if index < len(relative_paths) else None
        try:
            if extension != "zip":
                accepted.append(
                    await _queue_one(
                        db,
                        upload=upload,
                        area_id=area_uuid,
                        parent_id=folder_uuid,
                        relative_path=base_path,
                        admin=admin,
                        batch_id=batch_id,
                        title=title if len(files) == 1 else None,
                    )
                )
                continue

            await upload.seek(0)
            with zipfile.ZipFile(upload.file) as archive:
                entries = [info for info in archive.infolist() if not info.is_dir()]
                if len(entries) > 10_000:
                    raise StorageError("El ZIP supera 10.000 archivos")
                if (
                    sum(info.file_size for info in entries)
                    > settings_row.max_batch_bytes
                ):
                    raise StorageError(
                        "El contenido expandido del ZIP supera el límite del lote"
                    )
                for info in entries:
                    raw_name = info.filename.replace("\\", "/")
                    path = PurePosixPath(raw_name)
                    member_ext = path.suffix.lower().lstrip(".")
                    mode = info.external_attr >> 16
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or info.flag_bits & 1
                        or stat.S_ISLNK(mode)
                    ):
                        rejected.append(
                            {"filename": raw_name, "reason": "Entrada ZIP insegura"}
                        )
                        continue
                    if member_ext not in ALLOWED_EXTENSIONS:
                        rejected.append(
                            {
                                "filename": raw_name,
                                "reason": f"Formato .{member_ext or '?'} no admitido",
                            }
                        )
                        continue
                    if info.file_size > settings_row.max_file_bytes:
                        rejected.append(
                            {
                                "filename": raw_name,
                                "reason": "Supera el límite por archivo",
                            }
                        )
                        continue
                    if info.compress_size and info.file_size / info.compress_size > 200:
                        rejected.append(
                            {
                                "filename": raw_name,
                                "reason": "Relación de compresión insegura",
                            }
                        )
                        continue
                    member_path = "/".join(
                        part for part in path.parent.parts if part not in {".", ""}
                    )
                    combined_path = "/".join(
                        part for part in [base_path, member_path] if part
                    )
                    try:
                        with archive.open(info, "r") as member:
                            member_upload = UploadFile(
                                file=member, filename=path.name, size=info.file_size
                            )
                            accepted.append(
                                await _queue_one(
                                    db,
                                    upload=member_upload,
                                    area_id=area_uuid,
                                    parent_id=folder_uuid,
                                    relative_path=combined_path or None,
                                    admin=admin,
                                    batch_id=batch_id,
                                )
                            )
                    except (DocumentDomainError, StorageError, ValueError) as exc:
                        rejected.append({"filename": raw_name, "reason": str(exc)})
        except (
            zipfile.BadZipFile,
            DocumentDomainError,
            StorageError,
            ValueError,
        ) as exc:
            rejected.append({"filename": filename, "reason": str(exc)})

    return UploadBatchOut(batch_id=str(batch_id), accepted=accepted, rejected=rejected)


@router.get("/stats", response_model=RagStatsOut)
async def stats(db: AsyncSession = Depends(get_db)):
    status_rows = dict(
        (
            await db.execute(
                select(Document.status, func.count(Document.id)).group_by(
                    Document.status
                )
            )
        ).all()
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_(None))
        )
    ).scalar_one()
    chunks = (
        await db.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.is_retrievable.is_(True))
        )
    ).scalar_one()  # noqa: E712
    stored_blobs = (
        select(DocumentBlob.id, DocumentBlob.size_bytes)
        .join(DocumentVersion, DocumentVersion.blob_id == DocumentBlob.id)
        .where(DocumentVersion.status != "failed")
        .distinct()
        .subquery()
    )
    storage_bytes = (
        await db.execute(select(func.coalesce(func.sum(stored_blobs.c.size_bytes), 0)))
    ).scalar_one()
    queue_depth = (
        await db.execute(
            select(func.count())
            .select_from(DocumentIngestionJob)
            .where(DocumentIngestionJob.status.in_(["queued", "processing"]))
        )
    ).scalar_one()
    worker_last = (
        await db.execute(
            select(RagSettings.worker_last_heartbeat).where(
                RagSettings.key == "default"
            )
        )
    ).scalar_one_or_none()
    return RagStatsOut(
        documents_total=total,
        published=status_rows.get("published", 0),
        processing=status_rows.get("processing", 0),
        failed=status_rows.get("failed", 0),
        deleted=status_rows.get("deleted", 0),
        chunks=chunks,
        storage_bytes=storage_bytes,
        queue_depth=queue_depth,
        worker_last_activity=worker_last,
    )


@router.get("/settings", response_model=RagSettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    row = await rag_settings_service.require(db)
    return RagSettingsOut(
        **{name: getattr(row, name) for name in RagSettingsOut.model_fields}
    )


@router.patch(
    "/settings",
    response_model=RagSettingsOut,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_SETTINGS))],
)
async def update_settings(
    data: RagSettingsUpdate,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_SETTINGS)),
    db: AsyncSession = Depends(get_db),
):
    row = await rag_settings_service.require(db)
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(row, key, value)
    if row.chunk_overlap_tokens >= row.chunk_tokens:
        raise HTTPException(
            status_code=422, detail="El solapamiento debe ser menor al tamaño del chunk"
        )
    if row.max_batch_bytes < row.max_file_bytes:
        raise HTTPException(
            status_code=422,
            detail="El límite del lote no puede ser menor al límite por archivo",
        )
    if abs((row.vector_weight + row.lexical_weight) - 1.0) > 0.0001:
        raise HTTPException(
            status_code=422, detail="Los pesos vectorial y léxico deben sumar 1"
        )
    tool = (
        await db.execute(
            select(ToolConfig).where(ToolConfig.tool_name == "rag_documento_enviar")
        )
    ).scalar_one_or_none()
    if tool is not None and "enabled" in payload:
        tool.is_enabled = row.enabled
    db.add(
        DocumentEvent(
            actor_admin_id=admin.id,
            event_type="settings_updated",
            event_metadata={"fields": sorted(payload)},
        )
    )
    await db.flush()
    return RagSettingsOut(
        **{name: getattr(row, name) for name in RagSettingsOut.model_fields}
    )


@router.post("/search", response_model=list[RagSearchHitOut])
async def test_search(data: RagSearchRequest, db: AsyncSession = Depends(get_db)):
    user_id = _uuid(data.user_id, "Usuario")
    area_override = (
        {_uuid(value, "Área") for value in data.area_ids} if data.area_ids else None
    )
    if user_id is None and area_override is None:
        area_override = set(
            (
                await db.execute(
                    select(OrganizationArea.id).where(
                        OrganizationArea.is_active.is_(True)
                    )  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
    hits = await rag_retrieval_service.search(
        db,
        query=data.query,
        user_id=user_id,
        request_id=f"panel-{uuid.uuid4()}",
        area_ids_override=area_override,
        allow_disabled=True,
    )
    return [
        RagSearchHitOut(
            reference_code=hit.reference_code,
            title=hit.title,
            version_number=hit.version_number,
            content=hit.content,
            page_number=hit.page_number,
            location_label=hit.location_label,
            section_title=hit.section_title,
            score=hit.score,
        )
        for hit in hits
    ]


@router.get("/", response_model=DocumentListOut)
async def list_documents(
    q: str | None = None,
    area_id: str | None = None,
    folder_id: str | None = None,
    state: str | None = Query(default=None, alias="status"),
    include_deleted: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if not include_deleted:
        filters.append(Document.deleted_at.is_(None))
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                Document.title.ilike(term),
                Document.reference_code.ilike(term),
                Document.internal_code.ilike(term),
            )
        )
    if area_id:
        filters.append(DocumentFolder.area_id == _uuid(area_id, "Área"))
    if folder_id:
        filters.append(Document.folder_id == _uuid(folder_id, "Carpeta"))
    if state:
        filters.append(Document.status == state)
    base = _document_list_base(filters)
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Document.updated_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    document_ids = [document.id for document, _, _ in rows]
    current_by_document: dict[uuid.UUID, DocumentVersion] = {}
    latest_job_by_document: dict[uuid.UUID, DocumentIngestionJob] = {}
    if document_ids:
        current_versions = (
            (
                await db.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id.in_(document_ids),
                        DocumentVersion.is_current == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        current_by_document = {
            version.document_id: version for version in current_versions
        }
        latest_jobs = (
            await db.execute(
                select(DocumentVersion.document_id, DocumentIngestionJob)
                .join(
                    DocumentIngestionJob,
                    DocumentIngestionJob.version_id == DocumentVersion.id,
                )
                .where(DocumentVersion.document_id.in_(document_ids))
                .distinct(DocumentVersion.document_id)
                .order_by(
                    DocumentVersion.document_id, DocumentIngestionJob.created_at.desc()
                )
            )
        ).all()
        latest_job_by_document = {document_id: job for document_id, job in latest_jobs}
    items = [
        _build_document_out(
            document,
            folder,
            area,
            current_by_document.get(document.id),
            latest_job_by_document.get(document.id),
        )
        for document, folder, area in rows
    ]
    return DocumentListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    row = await _get_document_row(db, _uuid(document_id, "Documento"))
    return await _document_out(db, *row)


@router.get("/{document_id}/versions", response_model=list[VersionOut])
async def list_document_versions(document_id: str, db: AsyncSession = Depends(get_db)):
    document, _, _ = await _get_document_row(db, _uuid(document_id, "Documento"))
    versions = (
        (
            await db.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_version_out(version) for version in versions]


@router.patch(
    "/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE))],
)
async def update_document(
    document_id: str,
    data: DocumentUpdate,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    document, folder, area = await _get_document_row(
        db, _uuid(document_id, "Documento"), include_deleted=False
    )
    payload = data.model_dump(exclude_unset=True)
    changed_fields = sorted(payload)
    previous_folder_id = document.folder_id
    new_folder_id = payload.pop("folder_id", None)
    if new_folder_id:
        target = (
            await db.execute(
                select(DocumentFolder).where(
                    DocumentFolder.id == _uuid(new_folder_id, "Carpeta")
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=422, detail="Carpeta destino inexistente")
        document.folder_id = target.id
        folder = target
        area = (
            await db.execute(
                select(OrganizationArea).where(OrganizationArea.id == target.area_id)
            )
        ).scalar_one()
        await db.execute(
            DocumentChunk.__table__.update()
            .where(
                DocumentChunk.version_id.in_(
                    select(DocumentVersion.id).where(
                        DocumentVersion.document_id == document.id
                    )
                )
            )
            .values(area_id=target.area_id)
        )
    for key, value in payload.items():
        setattr(document, key, value)
    db.add(
        DocumentEvent(
            document_id=document.id,
            actor_admin_id=admin.id,
            event_type="metadata_updated",
            event_metadata={
                "fields": changed_fields,
                "previous_folder_id": str(previous_folder_id),
                "folder_id": str(document.folder_id),
            },
        )
    )
    await db.flush()
    # ``updated_at`` se actualiza en PostgreSQL y queda expirado tras el flush.
    # Refrescar evita que la serialización dispare IO implícito fuera del greenlet.
    await db.refresh(document)
    return await _document_out(db, document, folder, area)


@router.post(
    "/{document_id}/replace",
    response_model=UploadBatchOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE))],
)
async def replace_document(
    document_id: str,
    file: UploadFile = File(...),
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    document, folder, _ = await _get_document_row(
        db, _uuid(document_id, "Documento"), include_deleted=False
    )
    batch_id = uuid.uuid4()
    try:
        doc, version, job, duplicate = await rag_document_service.queue_upload(
            db,
            upload=file,
            folder=folder,
            admin=admin,
            batch_id=batch_id,
            document_id=document.id,
        )
    except (DocumentDomainError, StorageError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return UploadBatchOut(
        batch_id=str(batch_id),
        accepted=[
            UploadItemOut(
                document_id=str(doc.id),
                reference_code=doc.reference_code,
                version_id=str(version.id),
                job_id=str(job.id),
                filename=version.original_filename,
                duplicate_hash=duplicate,
            )
        ],
    )


@router.post(
    "/{document_id}/reindex",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE))],
)
async def reindex_document(
    document_id: str,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    document, _, _ = await _get_document_row(
        db, _uuid(document_id, "Documento"), include_deleted=False
    )
    try:
        _, job = await rag_document_service.queue_reindex(
            db, document=document, actor_admin_id=admin.id
        )
    except DocumentDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_out(job)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE))],
)
async def delete_document(
    document_id: str,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    document, _, _ = await _get_document_row(
        db, _uuid(document_id, "Documento"), include_deleted=False
    )
    await rag_document_service.soft_delete(
        db, document=document, actor_admin_id=admin.id
    )


@router.post(
    "/{document_id}/restore",
    response_model=DocumentOut,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE))],
)
async def restore_document(
    document_id: str,
    admin: AdminUser = Depends(require_permission(AdminPermission.DOCUMENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    document, folder, area = await _get_document_row(
        db, _uuid(document_id, "Documento")
    )
    await rag_document_service.restore(db, document=document, actor_admin_id=admin.id)
    await db.flush()
    await db.refresh(document)
    return await _document_out(db, document, folder, area)


@router.get("/{document_id}/download")
async def download_document(
    document_id: str, version_id: str | None = None, db: AsyncSession = Depends(get_db)
):
    document, _, _ = await _get_document_row(db, _uuid(document_id, "Documento"))
    query = (
        select(DocumentVersion, DocumentBlob)
        .join(DocumentBlob)
        .where(DocumentVersion.document_id == document.id)
    )
    if version_id:
        query = query.where(DocumentVersion.id == _uuid(version_id, "Versión"))
    else:
        query = query.where(DocumentVersion.is_current == True)  # noqa: E712
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Versión no disponible")
    version, blob = row
    path = document_storage.path_for(blob.storage_key)
    if not path.is_file():
        raise HTTPException(
            status_code=410, detail="El archivo original ya no está disponible"
        )
    return FileResponse(
        path=path, media_type=version.mime_type, filename=version.original_filename
    )
