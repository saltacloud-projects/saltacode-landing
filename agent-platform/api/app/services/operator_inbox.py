"""Read model for the agent-scoped operator inbox."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.conversation_control import ConversationControlEvent
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.schemas.conversation_control import ConversationControlEventOut
from app.schemas.operator_inbox import (
    AutomationAssignmentEventOut,
    InboxAgentOut,
    InboxConversationOut,
    InboxMessageOut,
    InboxOperatorOut,
    InboxThreadOut,
)
from app.services.admin_rbac import AdminPermission
from app.services.conversation_control import ConversationNotFoundError


@dataclass(frozen=True)
class InboxPage:
    items: list[InboxConversationOut]
    total: int


@dataclass(frozen=True)
class AutomationAssignmentHistoryPage:
    items: list[AutomationAssignmentEventOut]
    total: int


class OperatorInboxService:
    """Build an operational projection without moving policy into the router."""

    async def list_conversations(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        channel: str | None = None,
        control_mode: str | None = None,
        status: str | None = None,
        assigned_admin_id: uuid.UUID | None = None,
        unassigned_only: bool = False,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> InboxPage:
        await self._assert_agent_exists(db, agent_id)
        statement, message_count, last_activity = self._summary_statement(agent_id)
        statement = self._apply_filters(
            statement,
            last_activity=last_activity,
            channel=channel,
            control_mode=control_mode,
            status=status,
            assigned_admin_id=assigned_admin_id,
            unassigned_only=unassigned_only,
            updated_after=updated_after,
            updated_before=updated_before,
        )
        total = int(
            (
                await db.execute(select(func.count()).select_from(statement.subquery()))
            ).scalar_one()
        )
        rows = (
            await db.execute(
                statement.order_by(last_activity.desc(), ChatConversation.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return InboxPage(
            items=[
                self._conversation_out(
                    conversation,
                    principal,
                    assigned_operator,
                    routing_agent,
                    automation_agent,
                    int(count or 0),
                    activity,
                )
                for (
                    conversation,
                    principal,
                    assigned_operator,
                    routing_agent,
                    automation_agent,
                    count,
                    activity,
                ) in rows
            ],
            total=total,
        )

    async def get_thread(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_limit: int = 500,
    ) -> InboxThreadOut:
        statement, _, _ = self._summary_statement(agent_id)
        row = (
            await db.execute(statement.where(ChatConversation.id == conversation_id))
        ).one_or_none()
        if row is None:
            raise ConversationNotFoundError("conversation not found")
        (
            conversation,
            principal,
            assigned_operator,
            routing_agent,
            automation_agent,
            count,
            activity,
        ) = row
        messages = list(
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                    .limit(message_limit)
                )
            )
            .scalars()
            .all()
        )
        messages.reverse()
        events = list(
            (
                await db.execute(
                    select(ConversationControlEvent)
                    .where(
                        ConversationControlEvent.conversation_id == conversation_id,
                        ConversationControlEvent.agent_id == agent_id,
                    )
                    .order_by(
                        ConversationControlEvent.control_version,
                        ConversationControlEvent.created_at,
                    )
                )
            )
            .scalars()
            .all()
        )
        return InboxThreadOut(
            conversation=self._conversation_out(
                conversation,
                principal,
                assigned_operator,
                routing_agent,
                automation_agent,
                int(count or 0),
                activity,
            ),
            messages=[self._message_out(message) for message in messages],
            control_events=[
                ConversationControlEventOut.from_model(event) for event in events
            ],
        )

    async def list_automation_assignments(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> AutomationAssignmentHistoryPage:
        await self._assert_conversation_exists(
            db,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )
        from_agent = aliased(AgentProfile, name="assignment_from_agent")
        to_agent = aliased(AgentProfile, name="assignment_to_agent")
        scoped = (
            ConversationAutomationAssignmentEvent.conversation_id == conversation_id
        )
        total = int(
            (
                await db.execute(
                    select(func.count(ConversationAutomationAssignmentEvent.id)).where(
                        scoped,
                        ConversationAutomationAssignmentEvent.routing_agent_id
                        == agent_id,
                    )
                )
            ).scalar_one()
        )
        rows = (
            await db.execute(
                select(
                    ConversationAutomationAssignmentEvent,
                    from_agent,
                    to_agent,
                )
                .join(
                    from_agent,
                    from_agent.id
                    == ConversationAutomationAssignmentEvent.from_automation_agent_id,
                )
                .join(
                    to_agent,
                    to_agent.id
                    == ConversationAutomationAssignmentEvent.to_automation_agent_id,
                )
                .where(
                    scoped,
                    ConversationAutomationAssignmentEvent.routing_agent_id == agent_id,
                )
                .order_by(
                    ConversationAutomationAssignmentEvent.created_at.desc(),
                    ConversationAutomationAssignmentEvent.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return AutomationAssignmentHistoryPage(
            items=[
                self._automation_assignment_out(event, previous_agent, next_agent)
                for event, previous_agent, next_agent in rows
            ],
            total=total,
        )

    async def list_operators(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
    ) -> list[InboxOperatorOut]:
        await self._assert_agent_exists(db, agent_id)
        rows = (
            await db.execute(
                select(AdminUser, AdminRole.permissions)
                .join(AdminRole, AdminRole.key == AdminUser.role)
                .where(
                    AdminUser.is_active.is_(True),
                    AdminRole.is_active.is_(True),
                )
                .order_by(AdminUser.name, AdminUser.email)
            )
        ).all()
        required = AdminPermission.CONVERSATIONS_MANAGE.value
        return [
            InboxOperatorOut(id=user.id, name=user.name, email=user.email)
            for user, permissions in rows
            if isinstance(permissions, list)
            and (AdminPermission.ALL.value in permissions or required in permissions)
        ]

    @staticmethod
    def _summary_statement(
        agent_id: uuid.UUID,
    ) -> tuple[Select, object, object]:
        message_stats = (
            select(
                ChatMessage.conversation_id.label("conversation_id"),
                func.count(ChatMessage.id).label("message_count"),
                func.max(ChatMessage.created_at).label("last_message_at"),
            )
            .group_by(ChatMessage.conversation_id)
            .subquery()
        )
        message_count = func.coalesce(message_stats.c.message_count, 0)
        last_activity = func.coalesce(
            message_stats.c.last_message_at,
            ChatConversation.updated_at,
        )
        assigned_operator = aliased(AdminUser, name="assigned_operator")
        routing_agent = aliased(AgentProfile, name="routing_agent")
        automation_agent = aliased(AgentProfile, name="automation_agent")
        statement = (
            select(
                ChatConversation,
                Principal,
                assigned_operator,
                routing_agent,
                automation_agent,
                message_count,
                last_activity,
            )
            .join(Principal, Principal.id == ChatConversation.principal_id)
            .join(routing_agent, routing_agent.id == ChatConversation.agent_id)
            .join(
                automation_agent,
                automation_agent.id == ChatConversation.automation_agent_id,
            )
            .outerjoin(
                message_stats,
                message_stats.c.conversation_id == ChatConversation.id,
            )
            .outerjoin(
                assigned_operator,
                assigned_operator.id == ChatConversation.assigned_admin_id,
            )
            .where(ChatConversation.agent_id == agent_id)
        )
        return statement, message_count, last_activity

    @staticmethod
    def _apply_filters(
        statement: Select,
        *,
        last_activity: object,
        channel: str | None,
        control_mode: str | None,
        status: str | None,
        assigned_admin_id: uuid.UUID | None,
        unassigned_only: bool,
        updated_after: datetime | None,
        updated_before: datetime | None,
    ) -> Select:
        if channel:
            statement = statement.where(ChatConversation.channel == channel)
        if control_mode:
            statement = statement.where(ChatConversation.control_mode == control_mode)
        if status:
            statement = statement.where(ChatConversation.status == status)
        if assigned_admin_id:
            statement = statement.where(
                ChatConversation.assigned_admin_id == assigned_admin_id
            )
        if unassigned_only:
            statement = statement.where(ChatConversation.assigned_admin_id.is_(None))
        if updated_after:
            statement = statement.where(last_activity >= updated_after)
        if updated_before:
            statement = statement.where(last_activity <= updated_before)
        return statement

    @staticmethod
    async def _assert_agent_exists(
        db: AsyncSession,
        agent_id: uuid.UUID,
    ) -> None:
        exists = (
            await db.execute(select(AgentProfile.id).where(AgentProfile.id == agent_id))
        ).scalar_one_or_none()
        if exists is None:
            raise ConversationNotFoundError("agent not found")

    @staticmethod
    async def _assert_conversation_exists(
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> None:
        exists = (
            await db.execute(
                select(ChatConversation.id).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise ConversationNotFoundError("conversation not found")

    @staticmethod
    def _conversation_out(
        conversation: ChatConversation,
        principal: Principal,
        assigned_operator: object | None,
        routing_agent: AgentProfile,
        automation_agent: AgentProfile,
        message_count: int,
        last_activity: datetime,
    ) -> InboxConversationOut:
        operator = None
        if assigned_operator is not None:
            operator = InboxOperatorOut(
                id=assigned_operator.id,
                name=assigned_operator.name,
                email=assigned_operator.email,
            )
        return InboxConversationOut(
            id=conversation.id,
            principal_id=conversation.principal_id,
            display_name=principal.display_name,
            channel=conversation.channel,
            route_key=conversation.route_key,
            status=conversation.status,
            control_mode=conversation.control_mode,
            control_version=conversation.control_version,
            routing_agent=InboxAgentOut(
                id=routing_agent.id,
                name=routing_agent.name,
            ),
            automation_agent=InboxAgentOut(
                id=automation_agent.id,
                name=automation_agent.name,
            ),
            automation_version=conversation.automation_version,
            assigned_operator=operator,
            control_changed_at=conversation.control_changed_at,
            control_reason=conversation.control_reason,
            message_count=message_count,
            last_activity_at=last_activity,
        )

    @staticmethod
    def _message_out(message: ChatMessage) -> InboxMessageOut:
        metadata = message.metadata_json or {}
        actor_value = metadata.get("actor_admin_id")
        try:
            actor_admin_id = uuid.UUID(str(actor_value)) if actor_value else None
        except ValueError:
            actor_admin_id = None
        origin = metadata.get("origin")
        return InboxMessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            tool_names=list(message.tool_names or []),
            origin=str(origin) if origin else None,
            actor_admin_id=actor_admin_id,
            created_at=message.created_at,
        )

    @staticmethod
    def _automation_assignment_out(
        event: ConversationAutomationAssignmentEvent,
        from_agent: AgentProfile,
        to_agent: AgentProfile,
    ) -> AutomationAssignmentEventOut:
        return AutomationAssignmentEventOut(
            event_id=event.id,
            from_automation_agent=InboxAgentOut(
                id=from_agent.id,
                name=from_agent.name,
            ),
            to_automation_agent=InboxAgentOut(
                id=to_agent.id,
                name=to_agent.name,
            ),
            automation_version=event.automation_version,
            applied=event.applied,
            trigger=event.trigger,
            actor_admin_id=event.actor_admin_id,
            reason=event.reason,
            created_at=event.created_at,
        )


operator_inbox_service = OperatorInboxService()
