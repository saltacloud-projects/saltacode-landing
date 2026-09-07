"""Truthful execution activity shared by private conversation read projections."""

from sqlalchemy import and_, func, or_

from app.models.platform import ChatConversation, ChatExecution


def open_conversation_predicate():
    return and_(
        ChatConversation.status != "closed", ChatConversation.control_mode != "closed"
    )


def active_execution_predicate():
    """Only current automation may appear active; expired work is not typing."""
    return and_(
        open_conversation_predicate(),
        ChatConversation.control_mode == "automated",
        ChatExecution.automation_agent_id == ChatConversation.automation_agent_id,
        ChatExecution.control_version == ChatConversation.control_version,
        ChatExecution.automation_version == ChatConversation.automation_version,
        ChatExecution.output_message_id.is_(None),
        or_(
            ChatExecution.status == "queued",
            and_(
                ChatExecution.status == "running",
                ChatExecution.lease_owner.is_not(None),
                ChatExecution.lease_expires_at > func.now(),
            ),
        ),
    )
