"""Transactional policy for human ownership of channel-neutral conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_user import AdminUser
from app.models.conversation_control import ConversationControlEvent
from app.models.platform import ChatConversation, ChatMessage
from app.schemas.conversation_control import ConversationControlMode


class ConversationControlError(Exception):
    """Base error for conversation-control policy failures."""


class ConversationNotFoundError(ConversationControlError):
    """The conversation does not belong to the requested agent."""


class ControlVersionConflictError(ConversationControlError):
    """The caller acted on a stale control snapshot."""

    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"control version changed: expected {expected}, current {actual}"
        )


class InvalidControlTransitionError(ConversationControlError):
    """The requested transition violates the control state machine."""


class OperatorControlRequiredError(ConversationControlError):
    """A manual action was requested without ownership of the conversation."""


class AutomationBlockedError(ConversationControlError):
    """Automation is not allowed for the current control epoch."""


class ConversationControlService:
    """Serialize control changes and append an immutable event for each epoch."""

    _allowed_transitions = {
        ConversationControlMode.AUTOMATED: {
            ConversationControlMode.PAUSED,
            ConversationControlMode.HUMAN,
            ConversationControlMode.CLOSED,
        },
        ConversationControlMode.PAUSED: {
            ConversationControlMode.AUTOMATED,
            ConversationControlMode.HUMAN,
            ConversationControlMode.CLOSED,
        },
        ConversationControlMode.HUMAN: {
            ConversationControlMode.AUTOMATED,
            ConversationControlMode.PAUSED,
            ConversationControlMode.HUMAN,
            ConversationControlMode.CLOSED,
        },
        ConversationControlMode.CLOSED: set(),
    }

    async def get_snapshot(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> ChatConversation:
        return await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=False,
        )

    async def list_events(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ConversationControlEvent]:
        await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=False,
        )
        rows = await db.execute(
            select(ConversationControlEvent)
            .where(
                ConversationControlEvent.conversation_id == conversation_id,
                ConversationControlEvent.agent_id == agent_id,
            )
            .order_by(
                ConversationControlEvent.control_version,
                ConversationControlEvent.created_at,
            )
            .offset(offset)
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def transition(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        target_mode: ConversationControlMode,
        expected_version: int,
        assigned_admin_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> ChatConversation:
        conversation = await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=True,
        )
        self._assert_version(conversation, expected_version)

        current_mode = ConversationControlMode(conversation.control_mode)
        if target_mode not in self._allowed_transitions[current_mode]:
            raise InvalidControlTransitionError(
                f"cannot transition from {current_mode} to {target_mode}"
            )

        target_admin_id = await self._resolve_target_admin(
            db,
            actor_admin_id=actor_admin_id,
            current_mode=current_mode,
            current_admin_id=conversation.assigned_admin_id,
            target_mode=target_mode,
            requested_admin_id=assigned_admin_id,
        )
        event_type = self._event_type(
            current_mode=current_mode,
            target_mode=target_mode,
            current_admin_id=conversation.assigned_admin_id,
            target_admin_id=target_admin_id,
        )
        return await self._apply_control_epoch(
            db,
            conversation=conversation,
            actor_admin_id=actor_admin_id,
            target_mode=target_mode,
            target_admin_id=target_admin_id,
            event_type=event_type,
            reason=reason,
        )

    async def assert_automation_allowed(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        expected_version: int | None = None,
        for_update: bool = False,
    ) -> ChatConversation:
        conversation = await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=for_update,
        )
        if expected_version is not None:
            self._assert_version(conversation, expected_version)
        if conversation.control_mode != ConversationControlMode.AUTOMATED:
            raise AutomationBlockedError(
                f"automation is blocked while control mode is {conversation.control_mode}"
            )
        return conversation

    async def record_operator_message(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        content: str,
        expected_version: int,
    ) -> tuple[ChatConversation, ChatMessage]:
        conversation = await self._get_conversation(
            db,
            conversation_id=conversation_id,
            agent_id=agent_id,
            for_update=True,
        )
        self._assert_version(conversation, expected_version)
        if (
            conversation.control_mode != ConversationControlMode.HUMAN
            or conversation.assigned_admin_id != actor_admin_id
        ):
            raise OperatorControlRequiredError(
                "the authenticated operator does not control this conversation"
            )

        # Manual messages belong to the current ownership epoch. Advancing it here
        # would invalidate earlier messages that the future outbox has not sent yet.
        message_id = uuid.uuid4()
        message = ChatMessage(
            id=message_id,
            conversation_id=conversation.id,
            client_message_id=f"operator:{message_id}",
            role="assistant",
            content=content,
            status="pending_delivery",
            tool_names=[],
            metadata_json={
                "origin": "operator",
                "actor_admin_id": str(actor_admin_id),
                "control_version": conversation.control_version,
                "delivery": "not_attempted",
            },
        )
        db.add(message)
        await db.flush()
        return conversation, message

    async def _get_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        for_update: bool,
    ) -> ChatConversation:
        statement = select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.agent_id == agent_id,
        )
        if for_update:
            statement = statement.with_for_update()
        conversation = (await db.execute(statement)).scalar_one_or_none()
        if conversation is None:
            raise ConversationNotFoundError("conversation not found")
        return conversation

    @staticmethod
    def _assert_version(
        conversation: ChatConversation,
        expected_version: int,
    ) -> None:
        if conversation.control_version != expected_version:
            raise ControlVersionConflictError(
                expected=expected_version,
                actual=conversation.control_version,
            )

    async def _resolve_target_admin(
        self,
        db: AsyncSession,
        *,
        actor_admin_id: uuid.UUID,
        current_mode: ConversationControlMode,
        current_admin_id: uuid.UUID | None,
        target_mode: ConversationControlMode,
        requested_admin_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        if target_mode == ConversationControlMode.HUMAN:
            target_admin_id = requested_admin_id or actor_admin_id
            if (
                current_mode == ConversationControlMode.HUMAN
                and target_admin_id == current_admin_id
            ):
                raise InvalidControlTransitionError(
                    "human control is already assigned to this operator"
                )
            if target_admin_id != actor_admin_id:
                active_admin = (
                    await db.execute(
                        select(AdminUser.id).where(
                            AdminUser.id == target_admin_id,
                            AdminUser.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                if active_admin is None:
                    raise InvalidControlTransitionError(
                        "assigned operator does not exist or is inactive"
                    )
            return target_admin_id
        if requested_admin_id is not None:
            raise InvalidControlTransitionError(
                "assigned_admin_id is only valid for human control"
            )
        if target_mode == ConversationControlMode.PAUSED:
            return current_admin_id
        return None

    @staticmethod
    def _event_type(
        *,
        current_mode: ConversationControlMode,
        target_mode: ConversationControlMode,
        current_admin_id: uuid.UUID | None,
        target_admin_id: uuid.UUID | None,
    ) -> str:
        if target_mode == ConversationControlMode.PAUSED:
            return "paused"
        if target_mode == ConversationControlMode.AUTOMATED:
            return "resumed"
        if target_mode == ConversationControlMode.CLOSED:
            return "closed"
        if current_mode == ConversationControlMode.HUMAN:
            if target_admin_id == current_admin_id:
                raise InvalidControlTransitionError(
                    "human control reassignment requires another operator"
                )
            return "reassigned"
        return "taken_over"

    @staticmethod
    async def _apply_control_epoch(
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        actor_admin_id: uuid.UUID,
        target_mode: ConversationControlMode,
        target_admin_id: uuid.UUID | None,
        event_type: str,
        reason: str | None,
    ) -> ChatConversation:
        current_mode = conversation.control_mode
        current_admin_id = conversation.assigned_admin_id
        next_version = conversation.control_version + 1
        changed_at = datetime.now(UTC)

        conversation.control_mode = target_mode.value
        conversation.control_version = next_version
        conversation.assigned_admin_id = target_admin_id
        conversation.control_changed_at = changed_at
        conversation.control_reason = reason
        db.add(
            ConversationControlEvent(
                conversation_id=conversation.id,
                agent_id=conversation.agent_id,
                actor_admin_id=actor_admin_id,
                event_type=event_type,
                from_mode=current_mode,
                to_mode=target_mode.value,
                from_assigned_admin_id=current_admin_id,
                to_assigned_admin_id=target_admin_id,
                control_version=next_version,
                reason=reason,
                metadata_json={},
            )
        )
        await db.flush()
        return conversation


conversation_control_service = ConversationControlService()
