"""Read model for the agent-scoped operator inbox."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, String, cast, exists, false, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.conversation_control import ConversationControlEvent
from app.models.platform import ChatConversation, ChatExecution, ChatMessage, Principal
from app.schemas.conversation_control import ConversationControlEventOut
from app.schemas.operator_inbox import (
    AutomationAssignmentEventOut,
    InboxAgentOut,
    InboxConversationOut,
    InboxMessageFilters,
    InboxMessageOut,
    InboxOperatorOut,
    InboxThreadOut,
)
from app.services.admin_rbac import AdminPermission
from app.services.chat_execution_activity import open_conversation_predicate
from app.services.conversation_control import ConversationNotFoundError
from app.services.inbox_visibility import (
    enrich_inbox_visibility,
    unread_message_predicate,
)
from app.services.message_authorship import message_author_type


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
        agent_id: uuid.UUID | tuple[uuid.UUID, ...],
        admin_user_id: uuid.UUID | None = None,
        lifecycle: str = "all",
        message_filters: InboxMessageFilters | None = None,
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
        if isinstance(agent_id, uuid.UUID):
            await self._assert_agent_exists(db, agent_id)
        statement, message_count, last_activity, last_message_at = (
            self._summary_statement(agent_id)
        )
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
        filters = message_filters or InboxMessageFilters()
        if filters.last_message_from is not None:
            statement = statement.where(last_message_at >= filters.last_message_from)
        if filters.last_message_before is not None:
            statement = statement.where(last_message_at < filters.last_message_before)
        if filters.search:
            visible_label = func.coalesce(
                func.nullif(Principal.display_name, ""),
                func.concat(
                    "Visitante ", func.substr(cast(Principal.id, String), 1, 8)
                ),
            )
            statement = statement.where(
                visible_label.icontains(filters.search, autoescape=True)
            )
        if filters.unread_only:
            if admin_user_id is None:
                statement = statement.where(false())
            else:
                statement = statement.where(
                    exists(
                        select(ChatMessage.id).where(
                            ChatMessage.conversation_id == ChatConversation.id,
                            ChatMessage.role == "user",
                            unread_message_predicate(admin_user_id),
                        )
                    )
                )
        if lifecycle == "active":
            statement = statement.where(open_conversation_predicate())
        elif lifecycle == "history":
            statement = statement.where(~open_conversation_predicate())
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
        page = InboxPage(
            items=[
                self._conversation_out(
                    conversation,
                    principal,
                    assigned_operator,
                    routing_agent,
                    automation_agent,
                    int(count or 0),
                    activity,
                    last_message_at,
                    preview,
                    message_role,
                    message_origin,
                    has_execution,
                )
                for (
                    conversation,
                    principal,
                    assigned_operator,
                    routing_agent,
                    automation_agent,
                    count,
                    activity,
                    last_message_at,
                    preview,
                    message_role,
                    message_origin,
                    has_execution,
                ) in rows
            ],
            total=total,
        )
        await enrich_inbox_visibility(
            db, conversations=page.items, admin_user_id=admin_user_id
        )
        return page

    async def get_thread(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_limit: int = 500,
        admin_user_id: uuid.UUID | None = None,
    ) -> InboxThreadOut:
        statement, _, _, _ = self._summary_statement(agent_id)
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
            last_message_at,
            preview,
            message_role,
            message_origin,
            has_execution,
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
        execution_outputs = set(
            (
                await db.execute(
                    select(ChatExecution.output_message_id).where(
                        ChatExecution.conversation_id == conversation_id,
                        ChatExecution.output_message_id.in_(
                            [message.id for message in messages]
                        ),
                    )
                )
            ).scalars()
        )
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
        thread = InboxThreadOut(
            conversation=self._conversation_out(
                conversation,
                principal,
                assigned_operator,
                routing_agent,
                automation_agent,
                int(count or 0),
                activity,
                last_message_at,
                preview,
                message_role,
                message_origin,
                has_execution,
            ),
            messages=[
                self._message_out(
                    message, has_execution=message.id in execution_outputs
                )
                for message in messages
            ],
            control_events=[
                ConversationControlEventOut.from_model(event) for event in events
            ],
        )
        await enrich_inbox_visibility(
            db, conversations=[thread.conversation], admin_user_id=admin_user_id
        )
        return thread

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
        agent_id: uuid.UUID | tuple[uuid.UUID, ...],
    ) -> tuple[Select, object, object, object]:
        message_stats = (
            select(
                ChatMessage.conversation_id.label("conversation_id"),
                func.count(ChatMessage.id).label("message_count"),
                func.max(ChatMessage.created_at).label("last_message_at"),
            )
            .group_by(ChatMessage.conversation_id)
            .subquery()
        )
        output_proof = exists(
            select(ChatExecution.id).where(
                ChatExecution.output_message_id == ChatMessage.id,
                ChatExecution.conversation_id == ChatMessage.conversation_id,
            )
        )
        latest_message = (
            select(
                ChatMessage.created_at.label("last_message_at"),
                func.substr(
                    func.btrim(
                        func.regexp_replace(ChatMessage.content, r"\s+", " ", "g")
                    ),
                    1,
                    140,
                ).label("preview"),
                ChatMessage.role.label("message_role"),
                ChatMessage.metadata_json["origin"].astext.label("message_origin"),
                output_proof.label("has_execution"),
            )
            .where(ChatMessage.conversation_id == ChatConversation.id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
            .correlate(ChatConversation)
            .lateral("latest_inbox_message")
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
                latest_message.c.last_message_at,
                latest_message.c.preview,
                latest_message.c.message_role,
                latest_message.c.message_origin,
                latest_message.c.has_execution,
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
            .outerjoin(latest_message, true())
            .outerjoin(
                assigned_operator,
                assigned_operator.id == ChatConversation.assigned_admin_id,
            )
            .where(
                ChatConversation.agent_id.in_(
                    agent_id if isinstance(agent_id, tuple) else (agent_id,)
                )
            )
        )
        return statement, message_count, last_activity, message_stats.c.last_message_at

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
        last_message_at: datetime | None = None,
        last_message_preview: str | None = None,
        last_message_role: str | None = None,
        last_message_origin: str | None = None,
        has_execution: bool = False,
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
            last_message_at=last_message_at,
            last_message_preview=last_message_preview,
            last_message_author_type=(
                _inbox_author_type(
                    last_message_role, last_message_origin, bool(has_execution)
                )
                if last_message_at is not None
                else None
            ),
        )

    @staticmethod
    def _message_out(
        message: ChatMessage, *, has_execution: bool = False
    ) -> InboxMessageOut:
        metadata = message.metadata_json or {}
        actor_value = metadata.get("actor_admin_id")
        try:
            actor_admin_id = uuid.UUID(str(actor_value)) if actor_value else None
        except ValueError:
            actor_admin_id = None
        origin = metadata.get("origin")
        return InboxMessageOut(
            author_type=_inbox_author_type(message.role, origin, has_execution),
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


def _inbox_author_type(
    role: str | None, origin: str | None, has_execution: bool
) -> str:
    author = message_author_type(role or "", origin, has_execution)
    if author == "unknown" and role in {"system", "tool"}:
        return "system"
    return author


operator_inbox_service = OperatorInboxService()
