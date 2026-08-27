"""Importación inicial idempotente de un árbol documental al RAG.

Cada directorio de primer nivel se convierte en un área. El resto del árbol se
conserva como carpetas y cada archivo soportado se encola mediante el mismo
servicio de dominio utilizado por el panel.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.core.database import AsyncSessionLocal
from app.models.admin_user import AdminUser
from app.models.admin_role import AdminRole
from app.models.rag import (
    Document,
    DocumentBlob,
    DocumentEvent,
    DocumentFolder,
    DocumentVersion,
    OrganizationArea,
    RagSettings,
)
from app.services.rag.documents import rag_document_service
from app.services.rag.storage import ALLOWED_EXTENSIONS, StorageError, document_storage


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    result = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return (result or "area")[:100]


def _import_code(relative_path: Path) -> str:
    digest = hashlib.sha256(relative_path.as_posix().encode("utf-8")).hexdigest()[:32]
    return f"INITIAL-{digest}"


async def _get_or_create_area(db, name: str, actor_id: uuid.UUID) -> OrganizationArea:
    area = (await db.execute(
        select(OrganizationArea).where(OrganizationArea.name == name)
    )).scalar_one_or_none()
    if area is not None:
        return area

    base_slug = _slug(name)
    slug = base_slug
    if (await db.execute(
        select(OrganizationArea.id).where(OrganizationArea.slug == slug)
    )).scalar_one_or_none() is not None:
        suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
        slug = f"{base_slug[:91]}-{suffix}"
    area = OrganizationArea(
        name=name,
        slug=slug,
        description="Área creada por la importación documental inicial.",
    )
    db.add(area)
    await db.flush()
    db.add(DocumentEvent(
        actor_admin_id=actor_id,
        event_type="area_created",
        event_metadata={"area_id": str(area.id), "source": "initial_corpus_import"},
    ))
    return area


async def import_corpus(root: Path) -> None:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit("El directorio de importación no existe")

    files = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    supported = [path for path in files if path.suffix.lower().lstrip(".") in ALLOWED_EXTENSIONS]
    unsupported = len(files) - len(supported)
    batch_id = uuid.uuid4()
    queued = skipped = rejected = restored = 0

    area_roots: dict[str, tuple[uuid.UUID, uuid.UUID]] = {}
    async with AsyncSessionLocal() as db:
        admin = (await db.execute(
            select(AdminUser)
            .join(AdminRole, AdminRole.key == AdminUser.role)
            .where(
                AdminUser.is_active.is_(True),
                AdminRole.is_active.is_(True),
                AdminRole.permissions.contains(["*"]),
            )
            .order_by(AdminUser.created_at)
            .limit(1)
        )).scalar_one_or_none()
        if admin is None:
            raise SystemExit("No existe un administrador activo para auditar la importación")
        admin_id = admin.id

        general = (await db.execute(
            select(OrganizationArea).where(OrganizationArea.is_general.is_(True))
        )).scalar_one()
        max_file_bytes = (await db.execute(
            select(RagSettings.max_file_bytes).where(RagSettings.key == "default")
        )).scalar_one()
        area_names = sorted({
            path.relative_to(root).parts[0].strip()[:120]
            for path in supported
            if len(path.relative_to(root).parts) > 1
        })
        for area_name in area_names:
            area = await _get_or_create_area(db, area_name, admin_id)
            root_folder = await rag_document_service.ensure_folder_path(
                db,
                area_id=area.id,
                parent_id=None,
                relative_path=area.name,
            )
            area_roots[area_name] = (area.id, root_folder.id)
        general_root = await rag_document_service.ensure_folder_path(
            db,
            area_id=general.id,
            parent_id=None,
            relative_path=general.name,
        )
        area_roots["__general__"] = (general.id, general_root.id)
        await db.commit()

    for index, path in enumerate(supported, start=1):
        relative = path.relative_to(root)
        try:
            if len(relative.parts) > 1:
                area_key = relative.parts[0].strip()[:120]
                subdirectories = relative.parts[1:-1]
            else:
                area_key = "__general__"
                subdirectories = ()
            area_id, root_folder_id = area_roots[area_key]

            async with AsyncSessionLocal() as db:
                admin = await db.get(AdminUser, admin_id)
                root_folder = await db.get(DocumentFolder, root_folder_id)
                if admin is None or root_folder is None:
                    raise RuntimeError("El contexto persistido de la importación ya no existe")

                folder = root_folder
                if subdirectories:
                    folder = await rag_document_service.ensure_folder_path(
                        db,
                        area_id=area_id,
                        parent_id=root_folder.id,
                        relative_path="/".join(subdirectories),
                    )

                code = _import_code(relative)
                existing = (await db.execute(
                    select(Document.id, DocumentBlob)
                    .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                    .join(DocumentBlob, DocumentBlob.id == DocumentVersion.blob_id)
                    .where(Document.internal_code == code)
                    .order_by(DocumentVersion.version_number.desc())
                    .limit(1)
                )).one_or_none()
                if existing is not None:
                    _, blob = existing
                    if not document_storage.exists(blob.storage_key):
                        with path.open("rb") as source:
                            stored = document_storage.save_stream(
                                source,
                                path.name,
                                None,
                                max_file_bytes,
                            )
                        if stored.sha256 != blob.sha256:
                            document_storage.delete(stored.storage_key)
                            raise RuntimeError("El archivo fuente cambió desde la importación inicial")
                        restored += 1
                    skipped += 1
                    continue

                with path.open("rb") as source:
                    upload = UploadFile(file=source, filename=path.name, size=path.stat().st_size)
                    document, _, _, _ = await rag_document_service.queue_upload(
                        db,
                        upload=upload,
                        folder=folder,
                        admin=admin,
                        batch_id=batch_id,
                    )
                    document.internal_code = code
                await db.commit()
                queued += 1
        except Exception as exc:  # un archivo inválido no aborta el lote completo
            rejected += 1
            reason = str(exc)[:160] if isinstance(exc, StorageError) else type(exc).__name__
            print(f"rejected extension={path.suffix.lower() or '[none]'} reason={reason}")

        if index % 25 == 0 or index == len(supported):
            print(
                f"progress scanned={index}/{len(supported)} queued={queued} "
                f"skipped={skipped} restored={restored} rejected={rejected}"
            )

    print(
        f"complete batch_id={batch_id} supported={len(supported)} queued={queued} "
        f"skipped={skipped} restored={restored} rejected={rejected} unsupported={unsupported}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    asyncio.run(import_corpus(args.root))


if __name__ == "__main__":
    main()
