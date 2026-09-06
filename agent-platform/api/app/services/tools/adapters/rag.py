"""Tool nativa exclusiva para entregar un original RAG ya citado."""

import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.rag import Document, DocumentBlob, DocumentFolder, DocumentVersion
from app.schemas.tools import ToolExecutionContext, ToolResult
from app.services.rag.access import get_user_area_ids
from app.services.rag.settings import rag_settings_service
from app.services.rag.storage import document_storage
from app.services.tools.registry import AbstractTool

_REFERENCE_RE = re.compile(r"^DOC-[A-F0-9]{8}$")


class RagDocumentSendTool(AbstractTool):
    tool_name = "rag_documento_enviar"

    async def invoke(
        self,
        params: dict[str, Any],
        request_id: str,
        context: ToolExecutionContext | str | None,
    ) -> ToolResult:
        if (
            not isinstance(context, ToolExecutionContext)
            or context.channel != "whatsapp"
        ):
            return self._error(
                request_id, "The document is not available for this channel."
            )
        reference_code = str(params.get("reference_code") or "").strip().upper()
        if not _REFERENCE_RE.fullmatch(reference_code):
            return self._error(
                request_id,
                "Necesito la referencia exacta DOC-XXXXXXXX de una cita previa.",
            )

        async with AsyncSessionLocal() as db:
            rag_settings = await rag_settings_service.get(db)
            if rag_settings is None or not rag_settings.enabled:
                return self._error(
                    request_id, "La biblioteca documental no está habilitada."
                )
            try:
                user_id = uuid.UUID(context.principal_id or "")
                agent_id = uuid.UUID(context.agent_id or "")
            except ValueError:
                return self._error(
                    request_id, "El documento no está disponible para este usuario."
                )
            area_ids = await get_user_area_ids(db, user_id, agent_id)
            if not area_ids:
                return self._error(
                    request_id, "El documento no está disponible para este usuario."
                )
            row = (
                await db.execute(
                    select(Document, DocumentVersion, DocumentBlob)
                    .join(DocumentFolder, DocumentFolder.id == Document.folder_id)
                    .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                    .join(DocumentBlob, DocumentBlob.id == DocumentVersion.blob_id)
                    .where(
                        Document.reference_code == reference_code,
                        Document.deleted_at.is_(None),
                        Document.status == "published",
                        DocumentFolder.area_id.in_(area_ids),
                        DocumentVersion.is_current == True,  # noqa: E712
                        DocumentVersion.status == "ready",
                    )
                )
            ).one_or_none()
            if row is None:
                return self._error(
                    request_id, "El documento no está disponible para este usuario."
                )
            document, version, blob = row
            if not document_storage.exists(blob.storage_key):
                return self._error(
                    request_id, "El archivo original no está disponible temporalmente."
                )
            safe_name = (
                Path(version.original_filename)
                .name.replace("\r", "")
                .replace("\n", "")[:240]
            )
            return ToolResult(
                request_id=request_id,
                tool_name=self.tool_name,
                status="success",
                result={
                    "documento": document.title,
                    "referencia": document.reference_code,
                    "version": version.version_number,
                    "_archivo_adjunto": True,
                },
                file_storage_key=blob.storage_key,
                file_name=safe_name,
                file_mime=version.mime_type,
            )

    def _error(self, request_id: str, message: str) -> ToolResult:
        return ToolResult(
            request_id=request_id,
            tool_name=self.tool_name,
            status="error",
            error=message,
        )


def register_rag_tools(registry) -> None:
    registry.register(RagDocumentSendTool())
