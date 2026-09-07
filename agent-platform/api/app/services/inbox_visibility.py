"""Operator-specific unread projections and exact displayed-message acknowledgements."""

from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbox_read_receipt import InboxReadReceipt
from app.models.platform import ChatConversation, ChatExecution, ChatMessage
from app.schemas.operator_inbox import InboxAgentActivityOut, InboxConversationOut
from app.services.chat_execution_activity import active_execution_predicate
from app.services.conversation_control import ConversationNotFoundError


def unread_message_predicate(admin_user_id: UUID):
    return ~exists(
        select(InboxReadReceipt.message_id).where(
            InboxReadReceipt.admin_user_id == admin_user_id,
            InboxReadReceipt.message_id == ChatMessage.id,
        )
    )


async def enrich_inbox_visibility(
    db: AsyncSession,
    *,
    conversations: list[InboxConversationOut],
    admin_user_id: UUID | None,
) -> None:
    if not conversations:
        return
    ids = [item.id for item in conversations]
    latest = (
        await db.execute(
            select(ChatMessage.conversation_id, ChatMessage.id)
            .where(ChatMessage.conversation_id.in_(ids), ChatMessage.role == "user")
            .distinct(ChatMessage.conversation_id)
            .order_by(
                ChatMessage.conversation_id,
                ChatMessage.created_at.desc(),
                ChatMessage.id.desc(),
            )
        )
    ).all()
    latest_ids = dict(latest)
    unread = {}
    if admin_user_id is not None:
        unread = dict(
            (
                await db.execute(
                    select(ChatMessage.conversation_id, func.count(ChatMessage.id))
                    .where(
                        ChatMessage.conversation_id.in_(ids),
                        ChatMessage.role == "user",
                        unread_message_predicate(admin_user_id),
                    )
                    .group_by(ChatMessage.conversation_id)
                )
            ).all()
        )
    activities = (
        await db.execute(
            select(ChatExecution.conversation_id, ChatExecution.status)
            .join(
                ChatConversation, ChatConversation.id == ChatExecution.conversation_id
            )
            .where(ChatExecution.conversation_id.in_(ids), active_execution_predicate())
            .distinct(ChatExecution.conversation_id)
            .order_by(
                ChatExecution.conversation_id,
                (ChatExecution.status == "running").desc(),
                ChatExecution.created_at,
                ChatExecution.id,
            )
        )
    ).all()
    activity_by_conversation = dict(activities)
    for conversation in conversations:
        conversation.latest_inbound_message_id = latest_ids.get(conversation.id)
        conversation.unread_count = int(unread.get(conversation.id, 0))
        if activity := activity_by_conversation.get(conversation.id):
            conversation.agent_activity = InboxAgentActivityOut(
                status=activity,
                agent_id=conversation.automation_agent.id,
                name=conversation.automation_agent.name,
            )


async def mark_inbox_messages_read(
    db: AsyncSession,
    *,
    admin_user_id: UUID,
    agent_id: UUID,
    conversation_id: UUID,
    message_ids: list[UUID],
) -> int:
    """Never acknowledge an unseen concurrent commit using a time watermark."""
    selected_ids = set(message_ids)
    visible_ids = set(
        (
            await db.execute(
                select(ChatMessage.id)
                .join(
                    ChatConversation, ChatConversation.id == ChatMessage.conversation_id
                )
                .where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.agent_id == agent_id,
                    ChatMessage.id.in_(selected_ids),
                    ChatMessage.role == "user",
                )
            )
        ).scalars()
    )
    if visible_ids != selected_ids or not selected_ids:
        raise ConversationNotFoundError("conversation or inbound message not found")
    await db.execute(
        insert(InboxReadReceipt)
        .values(
            [
                {
                    "admin_user_id": admin_user_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                }
                for message_id in visible_ids
            ]
        )
        .on_conflict_do_nothing(index_elements=["admin_user_id", "message_id"])
    )
    return int(
        (
            await db.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.role == "user",
                    unread_message_predicate(admin_user_id),
                )
            )
        ).scalar_one()
    )
