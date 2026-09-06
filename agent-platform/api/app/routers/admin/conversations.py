"""Admin history for channel-neutral conversations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.agent_profile import AgentProfile
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.routers.admin.auth import require_permission
from app.schemas.admin import ConversationMessageOut, ConversationSummaryOut
from app.services.admin_rbac import AdminPermission

router = APIRouter(
    tags=["admin-conversations"],
    dependencies=[Depends(require_permission(AdminPermission.CONVERSATIONS_READ))],
)


@router.get("/", response_model=list[ConversationSummaryOut])
async def list_conversations(
    agent_id: uuid.UUID,
    channel: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    counts = (
        select(
            ChatMessage.conversation_id.label("conversation_id"),
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    stmt = (
        select(
            ChatConversation,
            AgentProfile.slug,
            Principal.display_name,
            counts.c.message_count,
            counts.c.last_message_at,
        )
        .join(AgentProfile, AgentProfile.id == ChatConversation.agent_id)
        .join(Principal, Principal.id == ChatConversation.principal_id)
        .outerjoin(counts, counts.c.conversation_id == ChatConversation.id)
        .where(ChatConversation.agent_id == agent_id)
        .order_by(
            func.coalesce(counts.c.last_message_at, ChatConversation.updated_at).desc()
        )
        .offset(offset)
        .limit(limit)
    )
    if channel:
        stmt = stmt.where(ChatConversation.channel == channel)
    rows = (await db.execute(stmt)).all()
    return [
        ConversationSummaryOut(
            id=str(conversation.id),
            agent_slug=agent_slug,
            principal_id=str(conversation.principal_id),
            display_name=display_name,
            channel=conversation.channel,
            route_key=conversation.route_key,
            external_thread_id=conversation.external_thread_id,
            status=conversation.status,
            message_count=message_count or 0,
            last_message_at=last_message_at,
            transcript_consent=conversation.transcript_consent,
            consent_version=conversation.consent_version,
        )
        for conversation, agent_slug, display_name, message_count, last_message_at in rows
    ]


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessageOut])
async def get_conversation_history(
    conversation_id: str,
    agent_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    conversation_uuid = _uuid_or_404(conversation_id)
    owned_conversation = (
        await db.execute(
            select(ChatConversation.id).where(
                ChatConversation.id == conversation_uuid,
                ChatConversation.agent_id == agent_id,
            )
        )
    ).scalar_one_or_none()
    if owned_conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = list(
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_uuid)
                .order_by(ChatMessage.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    messages.reverse()
    return [ConversationMessageOut.from_model(item) for item in messages]


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.CONVERSATIONS_MANAGE))],
)
async def delete_conversation(
    conversation_id: str,
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    conversation_uuid = _uuid_or_404(conversation_id)
    result = await db.execute(
        delete(ChatConversation).where(
            ChatConversation.id == conversation_uuid,
            ChatConversation.agent_id == agent_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return None


def _uuid_or_404(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
