"""Guardas de integración estática para el RAG persistente."""

import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.models.admin_user import AdminUser
from app.models.rag import DocumentChunk, DocumentFolder, DocumentVersion
from app.routers.admin.auth import require_admin_role
from app.routers.admin.documents import (
    _document_list_base,
    restore_document,
    update_document,
)
from app.schemas.tools import ToolExecutionContext, ToolResult
from app.services.rag.ingestion import RagIngestionWorker
from app.services.tools.adapters.rag import RagDocumentSendTool, register_rag_tools
from app.services.tools.registry import ToolRegistry

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


@pytest.mark.asyncio
async def test_viewer_cannot_mutate_admin_resources(monkeypatch):
    viewer = AdminUser(
        email="viewer@example.test",
        hashed_password="x",
        name="Viewer",
        role="viewer",
        is_active=True,
        must_change_password=False,
    )
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_rbac_service.has_permission",
        AsyncMock(return_value=False),
    )
    with pytest.raises(HTTPException) as exc:
        await require_admin_role(viewer, object())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_mutate_admin_resources(monkeypatch):
    admin = AdminUser(
        email="admin@example.test",
        hashed_password="x",
        name="Admin",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_rbac_service.has_permission",
        AsyncMock(return_value=True),
    )
    assert await require_admin_role(admin, object()) is admin


def test_rag_model_invariants_are_declared():
    folder_indexes = {index.name for index in DocumentFolder.__table__.indexes}
    version_indexes = {index.name for index in DocumentVersion.__table__.indexes}
    chunk_indexes = {index.name for index in DocumentChunk.__table__.indexes}
    assert "uq_document_folder_root" in folder_indexes
    assert "uq_document_version_current" in version_indexes
    assert "ix_document_chunks_embedding_hnsw" in chunk_indexes
    assert DocumentChunk.__table__.c.embedding.type.dim == 1536


def test_document_list_query_has_unambiguous_joins():
    query = _document_list_base([])
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "JOIN document_folders ON document_folders.id = documents.folder_id" in sql
    assert (
        "JOIN organization_areas ON organization_areas.id = document_folders.area_id"
        in sql
    )
    str(query.subquery().compile(dialect=postgresql.dialect()))


def test_document_update_refreshes_server_managed_timestamp_before_serializing():
    source = inspect.getsource(update_document)
    assert "await db.flush()" in source
    assert "await db.refresh(document)" in source
    assert source.index("await db.refresh(document)") < source.index(
        "return await _document_out"
    )


def test_document_restore_refreshes_server_managed_timestamp_before_serializing():
    source = inspect.getsource(restore_document)
    assert "await db.refresh(document)" in source
    assert source.index("await db.refresh(document)") < source.index(
        "return await _document_out"
    )


def test_final_ingestion_failure_preserves_original_blob():
    source = inspect.getsource(RagIngestionWorker._persist_failure)
    assert "document_storage.delete" not in source


def test_persistent_file_reference_is_never_serialized():
    result = ToolResult(
        request_id="r",
        tool_name="rag_documento_enviar",
        status="success",
        file_storage_key="blobs/aa/secret.pdf",
        file_name="manual.pdf",
        file_mime="application/pdf",
    )
    assert "file_storage_key" not in result.model_dump()
    assert "file_name" not in result.model_dump()


@pytest.mark.asyncio
async def test_document_delivery_requires_exact_cited_reference_without_db_access():
    result = await RagDocumentSendTool().invoke(
        {"reference_code": "manual-operativo"},
        "request",
        ToolExecutionContext(
            request_id="request",
            channel="whatsapp",
            external_subject="549test",
        ),
    )
    assert result.status == "error"
    assert "DOC-XXXXXXXX" in (result.error or "")
    assert result.file_storage_key is None


def test_rag_tool_registers_as_native_runtime_capability():
    registry = ToolRegistry()
    register_rag_tools(registry)
    assert isinstance(registry.get("rag_documento_enviar"), RagDocumentSendTool)


def test_frontend_and_compose_expose_complete_rag_surface():
    app_path = REPO_ROOT / "frontend/src/App.tsx"
    if not app_path.is_file():
        pytest.skip("El frontend no forma parte de la imagen runtime de FastAPI")
    app = app_path.read_text()
    page = (REPO_ROOT / "frontend/src/pages/Documents/index.tsx").read_text()
    client = (REPO_ROOT / "frontend/src/api/client.ts").read_text()
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert 'path="documents"' in app
    assert "webkitdirectory" in page and ".zip" in page
    assert 'data-testid="upload-submit"' in page
    assert "disabled={uploading}" in page
    assert "PERMISSIONS.DOCUMENTS_MANAGE" in page
    assert "options.body instanceof FormData" in client
    assert "rag-worker:" in compose
    assert "saltacode_agent_platform_documents" in compose


def test_platform_migration_creates_vector_and_document_schema():
    migration = (
        BACKEND_ROOT
        / "migrations_platform/versions/9ffe2a3e79cd_initial_agent_platform.py"
    ).read_text()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "document_chunks" in migration
    assert "ix_document_chunks_embedding_hnsw" in migration


def test_admin_roles_are_permission_driven_and_persisted():
    auth = (BACKEND_ROOT / "app/routers/admin/auth.py").read_text()
    rbac = (BACKEND_ROOT / "app/services/admin_rbac.py").read_text()
    bootstrap = (BACKEND_ROOT / "app/bootstrap.py").read_text()
    assert 'admin.role != "admin"' not in auth
    assert "AdminRole.permissions" in rbac
    assert 'ADMIN_PERMISSIONS = ["*"]' in bootstrap
    assert 'DOCUMENTS_MANAGE = "documents.manage"' in rbac
    layout_path = REPO_ROOT / "frontend/src/components/AdminLayout.tsx"
    if not layout_path.is_file():
        pytest.skip("El frontend no forma parte de la imagen runtime de FastAPI")
    layout = layout_path.read_text()
    assert "hasPermission(user, item.permission)" in layout
