"""Agent-scoped outbound delivery review and uncertainty resolution."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.deliveries import (
    DeliveryDetailOut,
    DeliveryPageOut,
    DeliveryResolutionMutationOut,
    DeliveryResolutionRequest,
    DeliveryStatus,
)
from app.services.admin_rbac import AdminPermission
from app.services.outbound_delivery_resolution import (
    DeliveryResolutionIdempotencyConflictError,
    DeliveryResolutionNotFoundError,
    DeliveryResolutionVersionConflictError,
    InvalidDeliveryResolutionError,
    outbound_delivery_resolution_service,
)
from app.services.outbound_delivery_review import (
    DeliveryReviewNotFoundError,
    outbound_delivery_review_service,
)

router = APIRouter(tags=["admin-deliveries"])


@router.get("/", response_model=DeliveryPageOut)
async def list_deliveries(
    agent_id: uuid.UUID,
    channel: str | None = Query(default=None, min_length=1, max_length=30),
    delivery_status: DeliveryStatus | None = Query(default=None, alias="status"),
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.DELIVERIES_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> DeliveryPageOut:
    page = await outbound_delivery_review_service.list_deliveries(
        db,
        agent_id=agent_id,
        channel=channel,
        delivery_status=delivery_status,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    return DeliveryPageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{delivery_id}", response_model=DeliveryDetailOut)
async def get_delivery(
    agent_id: uuid.UUID,
    delivery_id: uuid.UUID,
    _admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.DELIVERIES_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> DeliveryDetailOut:
    try:
        return await outbound_delivery_review_service.get_delivery(
            db,
            agent_id=agent_id,
            delivery_id=delivery_id,
        )
    except DeliveryReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        ) from exc


@router.post(
    "/{delivery_id}/resolve",
    response_model=DeliveryResolutionMutationOut,
)
async def resolve_delivery(
    agent_id: uuid.UUID,
    delivery_id: uuid.UUID,
    payload: DeliveryResolutionRequest,
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
        require_agent_permission(AdminPermission.DELIVERIES_REVIEW)
    ),
    db: AsyncSession = Depends(get_db),
) -> DeliveryResolutionMutationOut:
    try:
        result = await outbound_delivery_resolution_service.resolve(
            db,
            agent_id=agent_id,
            delivery_id=delivery_id,
            admin_id=admin.id,
            action=payload.action,
            expected_resolution_version=payload.expected_resolution_version,
            provider_message_id=payload.provider_message_id,
            evidence_source=payload.evidence_source,
            reason_code=payload.reason_code,
            idempotency_key=idempotency_key,
            correlation_id=(
                correlation_id.strip()
                if correlation_id and correlation_id.strip()
                else f"panel-{uuid.uuid4()}"
            ),
        )
    except DeliveryResolutionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        ) from exc
    except (
        DeliveryResolutionIdempotencyConflictError,
        DeliveryResolutionVersionConflictError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvalidDeliveryResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return DeliveryResolutionMutationOut(
        id=result.message.id,
        status=result.message.status,
        resolution_version=result.message.resolution_version,
        action=result.resolution.action,
        applied=result.applied,
    )
