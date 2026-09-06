"""Agent-scoped administration API for durable commercial follow-ups."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.commercial import FollowUpKindValue, FollowUpStatusValue
from app.schemas.follow_up_operations import (
    FollowUpCommandOut,
    FollowUpCommandRequest,
    FollowUpDetailOut,
    FollowUpEventPageOut,
    FollowUpQueuePageOut,
    FollowUpReviewResolutionRequest,
)
from app.services.admin_rbac import AdminPermission
from app.services.commercial.follow_up_read_models import (
    FollowUpReadNotFoundError,
    follow_up_read_service,
)
from app.services.commercial.follow_ups import (
    FollowUpConsentRequiredError,
    FollowUpIdempotencyConflictError,
    FollowUpNotFoundError,
    FollowUpVersionConflictError,
    InvalidFollowUpCommandError,
    follow_up_service,
)

router = APIRouter(
    tags=["admin-follow-ups"],
    dependencies=[Depends(require_agent_permission(AdminPermission.FOLLOW_UPS_READ))],
)


@router.get("/", response_model=FollowUpQueuePageOut)
async def list_follow_ups(
    agent_id: uuid.UUID,
    status_filter: FollowUpStatusValue | None = Query(default=None, alias="status"),
    kind: FollowUpKindValue | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> FollowUpQueuePageOut:
    page = await follow_up_read_service.list_tasks(
        db,
        agent_id=agent_id,
        status=status_filter,
        kind=kind,
        limit=limit,
        offset=offset,
    )
    return FollowUpQueuePageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=FollowUpDetailOut)
async def get_follow_up(
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FollowUpDetailOut:
    try:
        return await follow_up_read_service.get_task(
            db,
            agent_id=agent_id,
            task_id=task_id,
        )
    except FollowUpReadNotFoundError as exc:
        _raise_not_found(exc)


@router.get("/{task_id}/events", response_model=FollowUpEventPageOut)
async def list_follow_up_events(
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> FollowUpEventPageOut:
    try:
        page = await follow_up_read_service.list_events(
            db,
            agent_id=agent_id,
            task_id=task_id,
            limit=limit,
            offset=offset,
        )
    except FollowUpReadNotFoundError as exc:
        _raise_not_found(exc)
    return FollowUpEventPageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post("/{task_id}/cancel", response_model=FollowUpCommandOut)
async def cancel_follow_up(
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: FollowUpCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.FOLLOW_UPS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> FollowUpCommandOut:
    try:
        task = await follow_up_service.cancel(
            db,
            task_id=task_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            expected_version=payload.expected_version,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_follow_up_error(exc)
    return _command_out(task)


@router.post("/{task_id}/requeue", response_model=FollowUpCommandOut)
async def requeue_follow_up(
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: FollowUpCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.FOLLOW_UPS_REVIEW)
    ),
    db: AsyncSession = Depends(get_db),
) -> FollowUpCommandOut:
    task = await _resolve_review(
        db,
        agent_id=agent_id,
        task_id=task_id,
        admin=admin,
        expected_version=payload.expected_version,
        resolution="requeue",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    return _command_out(task)


@router.post("/{task_id}/review-resolution", response_model=FollowUpCommandOut)
async def resolve_follow_up_review(
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: FollowUpReviewResolutionRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.FOLLOW_UPS_REVIEW)
    ),
    db: AsyncSession = Depends(get_db),
) -> FollowUpCommandOut:
    task = await _resolve_review(
        db,
        agent_id=agent_id,
        task_id=task_id,
        admin=admin,
        expected_version=payload.expected_version,
        resolution=payload.resolution,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    return _command_out(task)


async def _resolve_review(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    admin: AdminUser,
    expected_version: int,
    resolution: str,
    correlation_id: str | None,
    idempotency_key: str,
):
    try:
        return await follow_up_service.resolve_review(
            db,
            task_id=task_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            expected_version=expected_version,
            resolution=resolution,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_follow_up_error(exc)


def _command_out(task) -> FollowUpCommandOut:
    return FollowUpCommandOut(
        id=task.id,
        status=task.status,
        state_version=task.state_version,
    )


def _correlation_id(value: str | None) -> str:
    normalized = (value or "").strip()
    return normalized or str(uuid.uuid4())


def _raise_not_found(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Follow-up task not found",
    ) from exc


def _raise_follow_up_error(exc: Exception) -> NoReturn:
    if isinstance(exc, (FollowUpReadNotFoundError, FollowUpNotFoundError)):
        _raise_not_found(exc)
    if isinstance(
        exc,
        (
            FollowUpVersionConflictError,
            FollowUpIdempotencyConflictError,
            FollowUpConsentRequiredError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, InvalidFollowUpCommandError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc
