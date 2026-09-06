"""Agent-scoped administration endpoints for live conversation operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.conversation_control import (
    ConversationControlMode,
    ConversationControlSnapshotOut,
    ConversationControlTransitionRequest,
    OperatorMessageOut,
    OperatorMessageRequest,
)
from app.schemas.operator_inbox import (
    InboxConversationPageOut,
    InboxOperatorOut,
    InboxThreadOut,
)
from app.services.admin_rbac import AdminPermission
from app.services.conversation_control import (
    ConversationControlError,
    ConversationNotFoundError,
    conversation_control_service,
)
from app.services.operator_inbox import operator_inbox_service

router = APIRouter(
    tags=["admin-operator-inbox"],
    dependencies=[
        Depends(require_agent_permission(AdminPermission.CONVERSATIONS_READ))
    ],
)


@router.get("/operators", response_model=list[InboxOperatorOut])
async def list_inbox_operators(
    agent_id: uuid.UUID,
    _admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> list[InboxOperatorOut]:
    try:
        return await operator_inbox_service.list_operators(db, agent_id=agent_id)
    except ConversationControlError as exc:
        _raise_http_error(exc)


@router.get("/", response_model=InboxConversationPageOut)
async def list_inbox_conversations(
    agent_id: uuid.UUID,
    channel: str | None = Query(default=None, min_length=1, max_length=30),
    control_mode: ConversationControlMode | None = None,
    conversation_status: str | None = Query(
        default=None,
        alias="status",
        min_length=1,
        max_length=30,
    ),
    assigned_admin_id: uuid.UUID | None = None,
    unassigned_only: bool = False,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> InboxConversationPageOut:
    if assigned_admin_id is not None and unassigned_only:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assigned_admin_id and unassigned_only are mutually exclusive",
        )
    try:
        page = await operator_inbox_service.list_conversations(
            db,
            agent_id=agent_id,
            channel=channel,
            control_mode=control_mode.value if control_mode else None,
            status=conversation_status,
            assigned_admin_id=assigned_admin_id,
            unassigned_only=unassigned_only,
            updated_after=updated_after,
            updated_before=updated_before,
            limit=limit,
            offset=offset,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return InboxConversationPageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=InboxThreadOut)
async def get_inbox_thread(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_limit: int = Query(default=500, ge=1, le=1_000),
    db: AsyncSession = Depends(get_db),
) -> InboxThreadOut:
    try:
        return await operator_inbox_service.get_thread(
            db,
            agent_id=agent_id,
            conversation_id=conversation_id,
            message_limit=message_limit,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)


@router.post(
    "/{conversation_id}/control-transitions",
    response_model=ConversationControlSnapshotOut,
)
async def transition_inbox_conversation(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: ConversationControlTransitionRequest,
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> ConversationControlSnapshotOut:
    try:
        conversation = await conversation_control_service.transition(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            actor_admin_id=admin.id,
            target_mode=payload.target_mode,
            expected_version=payload.expected_version,
            assigned_admin_id=payload.assigned_admin_id,
            reason=payload.reason,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return ConversationControlSnapshotOut.from_model(conversation)


@router.post(
    "/{conversation_id}/operator-messages",
    response_model=OperatorMessageOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_inbox_operator_message(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: OperatorMessageRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> OperatorMessageOut:
    try:
        (
            conversation,
            message,
            delivery,
        ) = await conversation_control_service.record_operator_message(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            actor_admin_id=admin.id,
            content=payload.content,
            expected_version=payload.expected_version,
            idempotency_key=idempotency_key,
        )
    except ConversationControlError as exc:
        _raise_http_error(exc)
    return OperatorMessageOut(
        message_id=message.id,
        delivery_status=delivery.delivery_status,
        control=ConversationControlSnapshotOut.from_model(conversation),
    )


def _raise_http_error(exc: ConversationControlError) -> NoReturn:
    if isinstance(exc, ConversationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation or agent not found",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc
