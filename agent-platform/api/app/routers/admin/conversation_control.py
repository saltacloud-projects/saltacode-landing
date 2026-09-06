"""Administration endpoints for scoped, auditable conversation control."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_permission
from app.schemas.conversation_control import (
    ConversationControlEventOut,
    ConversationControlSnapshotOut,
    ConversationControlTransitionRequest,
    OperatorMessageOut,
    OperatorMessageRequest,
)
from app.services.admin_rbac import AdminPermission
from app.services.conversation_control import (
    ConversationControlError,
    ConversationNotFoundError,
    conversation_control_service,
)

router = APIRouter(
    tags=["admin-conversation-control"],
    dependencies=[Depends(require_permission(AdminPermission.CONVERSATIONS_READ))],
)


@router.get(
    "/{conversation_id}/control",
    response_model=ConversationControlSnapshotOut,
)
async def get_conversation_control(
    conversation_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ConversationControlSnapshotOut:
    try:
        conversation = await conversation_control_service.get_snapshot(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return ConversationControlSnapshotOut.from_model(conversation)


@router.get(
    "/{conversation_id}/control-events",
    response_model=list[ConversationControlEventOut],
)
async def list_conversation_control_events(
    conversation_id: uuid.UUID,
    agent_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationControlEventOut]:
    try:
        events = await conversation_control_service.list_events(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            limit=limit,
            offset=offset,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return [ConversationControlEventOut.from_model(event) for event in events]


@router.post(
    "/{conversation_id}/control-transitions",
    response_model=ConversationControlSnapshotOut,
)
async def transition_conversation_control(
    conversation_id: uuid.UUID,
    data: ConversationControlTransitionRequest,
    agent_id: uuid.UUID,
    admin: AdminUser = Depends(
        require_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> ConversationControlSnapshotOut:
    try:
        conversation = await conversation_control_service.transition(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            actor_admin_id=admin.id,
            target_mode=data.target_mode,
            expected_version=data.expected_version,
            assigned_admin_id=data.assigned_admin_id,
            reason=data.reason,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return ConversationControlSnapshotOut.from_model(conversation)


@router.post(
    "/{conversation_id}/operator-messages",
    response_model=OperatorMessageOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_operator_message(
    conversation_id: uuid.UUID,
    data: OperatorMessageRequest,
    agent_id: uuid.UUID,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> OperatorMessageOut:
    try:
        (
            conversation,
            message,
            outbound,
        ) = await conversation_control_service.record_operator_message(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            actor_admin_id=admin.id,
            content=data.content,
            expected_version=data.expected_version,
            idempotency_key=idempotency_key,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return OperatorMessageOut(
        message_id=message.id,
        delivery_status=outbound.message.status,
        control=ConversationControlSnapshotOut.from_model(conversation),
    )


def _raise_http_error(exc: ConversationControlError) -> NoReturn:
    if isinstance(exc, ConversationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc
