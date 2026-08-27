"""Almacenamiento local content-addressed para originales RAG."""

import hashlib
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import BinaryIO

import filetype
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.config import settings
from app.services.rag.types import StoredFile

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "xlsx",
    "xlsm",
    "xls",
    "pptx",
    "txt",
    "md",
    "jpg",
    "jpeg",
    "png",
    "tif",
    "tiff",
}
ARCHIVE_EXTENSIONS = {"zip"}
_EXT_RE = re.compile(r"^[a-z0-9]{1,10}$")


class StorageError(ValueError):
    pass


class LocalDocumentStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.document_storage_root).resolve()
        self.blobs_root = self.root / "blobs"
        self.staging_root = self.root / "staging"

    async def ensure_ready(self) -> None:
        await run_in_threadpool(self._ensure_ready_sync)

    def ensure_ready_sync(self) -> None:
        self._ensure_ready_sync()

    def _ensure_ready_sync(self) -> None:
        self.blobs_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)

    async def save_upload(
        self,
        upload: UploadFile,
        *,
        max_bytes: int,
        allow_archive: bool = False,
    ) -> StoredFile:
        filename = upload.filename or "archivo"
        return await run_in_threadpool(
            self.save_stream,
            upload.file,
            filename,
            upload.content_type,
            max_bytes,
            allow_archive,
        )

    def save_stream(
        self,
        stream: BinaryIO,
        filename: str,
        declared_mime: str | None,
        max_bytes: int,
        allow_archive: bool = False,
    ) -> StoredFile:
        self._ensure_ready_sync()
        extension = self._extension(filename)
        allowed = ALLOWED_EXTENSIONS | (ARCHIVE_EXTENSIONS if allow_archive else set())
        if extension not in allowed:
            raise StorageError(f"Formato '.{extension or '?'}' no admitido")

        temp_path = self.staging_root / f"{uuid.uuid4().hex}.upload"
        digest = hashlib.sha256()
        total = 0
        header = b""
        try:
            with temp_path.open("xb") as target:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if not header:
                        header = chunk[:4096]
                    total += len(chunk)
                    if total > max_bytes:
                        raise StorageError(
                            f"El archivo supera el límite de {max_bytes} bytes"
                        )
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            if total == 0:
                raise StorageError("El archivo está vacío")
            mime_type = self._validated_mime(extension, header, declared_mime)
            sha256 = digest.hexdigest()
            storage_key = f"blobs/{sha256[:2]}/{sha256}.{extension}"
            final_path = self.path_for(storage_key)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            duplicate = final_path.exists()
            if duplicate:
                temp_path.unlink(missing_ok=True)
            else:
                os.replace(temp_path, final_path)
                final_path.chmod(0o640)
            return StoredFile(
                sha256=sha256,
                storage_key=storage_key,
                size_bytes=total,
                mime_type=mime_type,
                extension=extension,
                path=final_path,
                duplicate=duplicate,
            )
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def path_for(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError("Referencia de almacenamiento inválida")
        return candidate

    def open(self, storage_key: str, mode: str = "rb"):
        return self.path_for(storage_key).open(mode)

    def exists(self, storage_key: str) -> bool:
        return self.path_for(storage_key).is_file()

    def delete(self, storage_key: str) -> None:
        self.path_for(storage_key).unlink(missing_ok=True)

    def copy_to(self, storage_key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path_for(storage_key), destination)

    def cleanup_orphans(
        self,
        known_storage_keys: set[str],
        *,
        older_than_seconds: int = 86400,
    ) -> tuple[int, int]:
        """Elimina blobs sin fila DB y staging viejo, nunca archivos recientes."""
        self._ensure_ready_sync()
        cutoff = time.time() - older_than_seconds
        orphaned_blobs = 0
        stale_staging = 0
        for path in self.blobs_root.rglob("*"):
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            key = path.relative_to(self.root).as_posix()
            if key not in known_storage_keys:
                path.unlink(missing_ok=True)
                orphaned_blobs += 1
        for path in self.staging_root.glob("*.upload"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                stale_staging += 1
        return orphaned_blobs, stale_staging

    @staticmethod
    def _extension(filename: str) -> str:
        extension = Path(filename).suffix.lower().lstrip(".")
        if not _EXT_RE.fullmatch(extension):
            return ""
        return extension

    @staticmethod
    def _validated_mime(extension: str, header: bytes, declared: str | None) -> str:
        guessed = filetype.guess(header)
        detected = guessed.mime if guessed else None
        declared = (declared or "").split(";", 1)[0].strip().lower()

        if extension == "pdf" and not header.startswith(b"%PDF-"):
            raise StorageError("El contenido no corresponde a un PDF válido")
        if extension in {
            "docx",
            "xlsx",
            "xlsm",
            "pptx",
            "zip",
        } and not header.startswith(b"PK"):
            raise StorageError(
                "El contenido no corresponde a un contenedor Office/ZIP válido"
            )
        if extension == "xls" and header[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
            raise StorageError("El contenido no corresponde a un XLS válido")
        if extension in {"jpg", "jpeg", "png", "tif", "tiff"} and not (
            detected or ""
        ).startswith("image/"):
            raise StorageError("El contenido no corresponde a una imagen admitida")

        mime_by_extension = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
            "xls": "application/vnd.ms-excel",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "txt": "text/plain",
            "md": "text/markdown",
            "zip": "application/zip",
        }
        return (
            mime_by_extension.get(extension)
            or detected
            or declared
            or "application/octet-stream"
        )


document_storage = LocalDocumentStorage()
