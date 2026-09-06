"""Agent-scoped administration API for external-channel ingress review."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.channel_inbound import (
    ChannelInboundCommandRequest,
    ChannelInboundDetailOut,
    ChannelInboundMutationOut,
    ChannelInboundPageOut,
    ChannelInboundStatusValue,
    ChannelInboundTimelineOut,
)
from app.services.admin_rbac import AdminPermission
from app.services.channel_inbound_review import (
    ChannelInboundIdempotencyConflict,
    ChannelInboundNotFound,
    ChannelInboundVersionConflict,
    InvalidChannelInboundCommand,
    channel_inbound_review_service,
)

router = APIRouter(
    tags=["admin-channel-inbound"],
    dependencies=[Depends(require_agent_permission(AdminPermission.INBOUND_READ))],
)


@router.get("/", response_model=ChannelInboundPageOut)
async def list_channel_inbound(
    agent_id: uuid.UUID,
    status_filter: ChannelInboundStatusValue | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ChannelInboundPageOut:
    page = await channel_inbound_review_service.list_jobs(
        db,
        agent_id=agent_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return ChannelInboundPageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=ChannelInboundDetailOut)
async def get_channel_inbound(
    agent_id: uuid.UUID,
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ChannelInboundDetailOut:
    try:
        return await channel_inbound_review_service.get_job(
            db, agent_id=agent_id, job_id=job_id
        )
    except ChannelInboundNotFound as exc:
        _raise_not_found(exc)


@router.get("/{job_id}/timeline", response_model=ChannelInboundTimelineOut)
async def get_channel_inbound_timeline(
    agent_id: uuid.UUID,
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ChannelInboundTimelineOut:
    try:
        items = await channel_inbound_review_service.timeline(
            db, agent_id=agent_id, job_id=job_id
        )
    except ChannelInboundNotFound as exc:
        _raise_not_found(exc)
    return ChannelInboundTimelineOut(items=items)


@router.post("/{job_id}/requeue", response_model=ChannelInboundMutationOut)
async def requeue_channel_inbound(
    agent_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: ChannelInboundCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=220
    ),
    correlation_id: str | None = Header(
        default=None, alias="X-Correlation-ID", max_length=120
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.INBOUND_REVIEW)
    ),
    db: AsyncSession = Depends(get_db),
) -> ChannelInboundMutationOut:
    return await _command(
        channel_inbound_review_service.requeue,
        agent_id=agent_id,
        job_id=job_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


@router.post("/{job_id}/cancel", response_model=ChannelInboundMutationOut)
async def cancel_channel_inbound(
    agent_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: ChannelInboundCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=220
    ),
    correlation_id: str | None = Header(
        default=None, alias="X-Correlation-ID", max_length=120
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.INBOUND_REVIEW)
    ),
    db: AsyncSession = Depends(get_db),
) -> ChannelInboundMutationOut:
    return await _command(
        channel_inbound_review_service.cancel,
        agent_id=agent_id,
        job_id=job_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


@router.post("/{job_id}/acknowledge", response_model=ChannelInboundMutationOut)
async def acknowledge_channel_inbound(
    agent_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: ChannelInboundCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=220
    ),
    correlation_id: str | None = Header(
        default=None, alias="X-Correlation-ID", max_length=120
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.INBOUND_REVIEW)
    ),
    db: AsyncSession = Depends(get_db),
) -> ChannelInboundMutationOut:
    return await _command(
        channel_inbound_review_service.acknowledge,
        agent_id=agent_id,
        job_id=job_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


async def _command(
    operation,
    *,
    agent_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: ChannelInboundCommandRequest,
    idempotency_key: str,
    correlation_id: str | None,
    admin: AdminUser,
    db: AsyncSession,
) -> ChannelInboundMutationOut:
    try:
        job = await operation(
            db,
            agent_id=agent_id,
            job_id=job_id,
            admin_id=admin.id,
            expected_version=payload.expected_version,
            correlation_id=(correlation_id or str(uuid.uuid4())).strip(),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_error(exc)
    return ChannelInboundMutationOut(
        id=job.id,
        status=job.status,
        phase=job.phase,
        state_version=job.state_version,
        safe_code=job.safe_code,
    )


def _raise_not_found(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Inbound job not found",
    ) from exc


def _raise_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ChannelInboundNotFound):
        _raise_not_found(exc)
    if isinstance(
        exc,
        (ChannelInboundVersionConflict, ChannelInboundIdempotencyConflict),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, InvalidChannelInboundCommand):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc
