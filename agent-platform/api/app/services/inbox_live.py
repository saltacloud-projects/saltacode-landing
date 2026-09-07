"""Scoped, content-free live Inbox invalidation with per-operator unread totals."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbox_read_receipt import InboxReadReceipt
from app.models.platform import ChatConversation, ChatExecution, ChatMessage
from app.schemas.operator_inbox import InboxLiveSnapshotOut
from app.services.admin_agent_access import AgentOperationAccess
from app.services.chat_execution_activity import (
    active_execution_predicate,
    open_conversation_predicate,
)
from app.services.inbox_visibility import unread_message_predicate


def _fingerprint(*columns):
    # Order-independent metadata fingerprint: counts alone miss replies and ownership changes.
    return func.coalesce(
        func.sum(func.hashtextextended(func.concat_ws("|", *columns), 0)), 0
    )


async def inbox_live_snapshot(
    db: AsyncSession,
    *,
    admin_user_id: UUID,
    agents: list[AgentOperationAccess],
) -> InboxLiveSnapshotOut:
    ids = tuple(agent.agent_id for agent in agents)
    scope = ChatConversation.agent_id.in_(ids)
    conversation_stats = (
        await db.execute(
            select(
                func.count(ChatConversation.id),
                func.count(ChatConversation.id).filter(open_conversation_predicate()),
                _fingerprint(
                    ChatConversation.id,
                    ChatConversation.updated_at,
                    ChatConversation.status,
                    ChatConversation.control_mode,
                    ChatConversation.control_version,
                    ChatConversation.automation_version,
                    ChatConversation.automation_agent_id,
                    ChatConversation.assigned_admin_id,
                    ChatConversation.next_event_sequence,
                ),
            ).where(scope)
        )
    ).one()
    message_stats = (
        await db.execute(
            select(
                func.count(ChatMessage.id),
                _fingerprint(
                    ChatMessage.id, ChatMessage.updated_at, ChatMessage.status
                ),
            )
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .where(scope)
        )
    ).one()
    execution_stats = (
        await db.execute(
            select(
                func.count(ChatExecution.id),
                _fingerprint(
                    ChatExecution.id,
                    ChatExecution.status,
                    ChatExecution.updated_at,
                    case((active_execution_predicate(), 1), else_=0),
                ),
            )
            .join(
                ChatConversation, ChatConversation.id == ChatExecution.conversation_id
            )
            .where(scope)
        )
    ).one()
    receipt_count = (
        await db.execute(
            select(func.count(InboxReadReceipt.message_id))
            .join(
                ChatConversation,
                ChatConversation.id == InboxReadReceipt.conversation_id,
            )
            .where(scope, InboxReadReceipt.admin_user_id == admin_user_id)
        )
    ).scalar_one()
    unread_count = (
        await db.execute(
            select(func.count(func.distinct(ChatMessage.conversation_id)))
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .where(
                scope,
                open_conversation_predicate(),
                ChatMessage.role == "user",
                unread_message_predicate(admin_user_id),
            )
        )
    ).scalar_one()
    metadata = [
        [str(value) for value in conversation_stats],
        [str(value) for value in message_stats],
        [str(value) for value in execution_stats],
        receipt_count,
        unread_count,
        sorted(
            (str(agent.agent_id), agent.agent_name, sorted(agent.capabilities))
            for agent in agents
        ),
    ]
    revision = hashlib.sha256(json.dumps(metadata).encode()).hexdigest()
    return InboxLiveSnapshotOut(
        revision=revision,
        unread_conversations=int(unread_count),
        active_conversations=int(conversation_stats[1]),
        historical_conversations=int(conversation_stats[0] - conversation_stats[1]),
    )
