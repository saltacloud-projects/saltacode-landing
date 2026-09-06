"""Read-only, agent-scoped outbound delivery review endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.routers.admin.auth import require_agent_permission
from app.schemas.deliveries import (
    DeliveryDetailOut,
    DeliveryPageOut,
    DeliveryStatus,
)
from app.services.admin_rbac import AdminPermission
from app.services.outbound_delivery_review import (
    DeliveryReviewNotFoundError,
    outbound_delivery_review_service,
)

router = APIRouter(
    tags=["admin-deliveries"],
    dependencies=[Depends(require_agent_permission(AdminPermission.DELIVERIES_READ))],
)


@router.get("/", response_model=DeliveryPageOut)
async def list_deliveries(
    agent_id: uuid.UUID,
    channel: str | None = Query(default=None, min_length=1, max_length=30),
    delivery_status: DeliveryStatus | None = Query(default=None, alias="status"),
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
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
