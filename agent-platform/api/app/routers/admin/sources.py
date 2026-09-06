"""RBAC-protected administration of integration sources."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_permission
from app.schemas.integrations import (
    IntegrationSourceCreate,
    IntegrationSourceOut,
    IntegrationSourceTestRequest,
    IntegrationSourceTestResult,
    IntegrationSourceUpdate,
)
from app.services.admin_rbac import AdminPermission
from app.services.credentials import CredentialStoreUnavailable
from app.services.http_executor import SourceRequestError, restricted_http_executor
from app.services.integration_sources import integration_source_service

router = APIRouter(
    tags=["admin-sources"],
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_READ))],
)


async def _source_or_404(db: AsyncSession, source_id: str):
    try:
        parsed_id = uuid.UUID(source_id)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Credential encryption is unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="Integration source not found"
        ) from exc
    source = await integration_source_service.get(db, parsed_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Integration source not found")
    return source


@router.get("/", response_model=list[IntegrationSourceOut])
async def list_sources(db: AsyncSession = Depends(get_db)):
    return [
        IntegrationSourceOut.from_model(item)
        for item in await integration_source_service.list(db)
    ]


@router.post(
    "/",
    response_model=IntegrationSourceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_MANAGE))],
)
async def create_source(
    data: IntegrationSourceCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.SOURCES_MANAGE)),
):
    try:
        source = await integration_source_service.create(db, data, actor=admin.email)
        await db.commit()
        await db.refresh(source)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Integration source already exists"
        ) from exc
    return IntegrationSourceOut.from_model(source)


@router.patch(
    "/{source_id}",
    response_model=IntegrationSourceOut,
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_MANAGE))],
)
async def update_source(
    source_id: str,
    data: IntegrationSourceUpdate,
    db: AsyncSession = Depends(get_db),
):
    source = await _source_or_404(db, source_id)
    try:
        source = await integration_source_service.update(db, source, data)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Credential encryption is unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(source)
    return IntegrationSourceOut.from_model(source)


@router.post(
    "/{source_id}/test",
    response_model=IntegrationSourceTestResult,
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_MANAGE))],
)
async def test_source(
    source_id: str,
    data: IntegrationSourceTestRequest,
    db: AsyncSession = Depends(get_db),
):
    source = await _source_or_404(db, source_id)
    started = time.monotonic()
    try:
        response = await restricted_http_executor.execute(
            source, method="GET", path=data.path
        )
        return IntegrationSourceTestResult(
            ok=200 <= response.status_code < 500,
            status_code=response.status_code,
            duration_ms=response.duration_ms,
            content_type=response.headers.get("content-type"),
        )
    except SourceRequestError as exc:
        return IntegrationSourceTestResult(
            ok=False,
            status_code=exc.status_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code=exc.code,
        )
