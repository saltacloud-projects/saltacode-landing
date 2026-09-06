"""Consent and task fencing for commercial outbound delivery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact, ContactPoint
from app.models.follow_up import FollowUpTask
from app.models.opportunity import Opportunity
from app.models.outbound import OutboundMessage
from app.models.platform import ChatConversation
from app.services.commercial.consent_scope import (
    ConsentScope,
    acquire_consent_scope_lock,
)
from app.services.commercial.consents import ConsentPurpose, ConsentService
from app.services.commercial.contact_crypto import (
    ContactCrypto,
    ContactCryptoError,
    contact_crypto,
)

_ACTIVE_TASK_STATUSES = {"dispatch_queued", "in_progress"}
_CLOSED_OPPORTUNITY_STAGES = {"won", "lost"}
_Model = TypeVar("_Model")


class FollowUpDispatchBlocked(Exception):
    """A linked follow-up no longer has its exact delivery authorization."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class FollowUpDispatchAuthorizationService:
    """Fence optional follow-up work under its exact consent scope."""

    def __init__(
        self,
        *,
        consents: ConsentService | None = None,
        crypto: ContactCrypto = contact_crypto,
    ) -> None:
        self._consents = consents or ConsentService()
        self._crypto = crypto

    async def revalidate(
        self,
        db: AsyncSession,
        *,
        message: OutboundMessage,
    ) -> None:
        task = await self._find_task(db, outbound_message_id=message.id)
        if task is None:
            return
        graph = await self._load_graph(db, task=task)
        scope = self._scope(graph)
        await acquire_consent_scope_lock(db, scope=scope)

        task = await self._lock_task(db, task_id=task.id)
        graph = await self._load_graph(db, task=task, for_update=True)
        self._assert_task_and_target(graph, message=message)
        effective = await self._consents.effective(
            db,
            agent_id=graph.conversation.agent_id,
            principal_id=graph.contact.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            contact_point_id=graph.point.id,
            source_conversation_id=graph.conversation.id,
            target_channel=task.target_channel,
        )
        if not effective.granted or effective.record is None:
            raise FollowUpDispatchBlocked("follow_up_consent_missing")
        task.executed_consent_record_id = effective.record.id

    @staticmethod
    async def _find_task(
        db: AsyncSession,
        *,
        outbound_message_id: uuid.UUID,
    ) -> FollowUpTask | None:
        return (
            await db.execute(
                select(FollowUpTask).where(
                    FollowUpTask.outbound_message_id == outbound_message_id
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _lock_task(
        db: AsyncSession,
        *,
        task_id: uuid.UUID,
    ) -> FollowUpTask:
        task = (
            await db.execute(
                select(FollowUpTask)
                .where(FollowUpTask.id == task_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise FollowUpDispatchBlocked("follow_up_task_changed")
        return task

    async def _load_graph(
        self,
        db: AsyncSession,
        *,
        task: FollowUpTask,
        for_update: bool = False,
    ) -> _FollowUpGraph:
        opportunity = await self._load(
            db,
            Opportunity,
            task.opportunity_id,
            for_update=for_update,
        )
        conversation = await self._load(
            db,
            ChatConversation,
            task.conversation_id,
            for_update=for_update,
        )
        contact = await self._load(
            db,
            Contact,
            opportunity.contact_id if opportunity else None,
            for_update=for_update,
        )
        point = await self._load(
            db,
            ContactPoint,
            task.contact_point_id,
            for_update=for_update,
        )
        if None in (opportunity, conversation, contact, point):
            raise FollowUpDispatchBlocked("follow_up_authorization_changed")
        return _FollowUpGraph(
            task=task,
            opportunity=opportunity,
            conversation=conversation,
            contact=contact,
            point=point,
        )

    @staticmethod
    async def _load(
        db: AsyncSession,
        model: type[_Model],
        object_id: uuid.UUID | None,
        *,
        for_update: bool,
    ) -> _Model | None:
        if object_id is None:
            return None
        statement = (
            select(model)
            .where(model.id == object_id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _scope(graph: _FollowUpGraph) -> ConsentScope:
        task = graph.task
        if task.target_channel is None:
            raise FollowUpDispatchBlocked("follow_up_authorization_changed")
        return ConsentScope(
            routing_agent_id=graph.conversation.agent_id,
            principal_id=graph.contact.principal_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            source_conversation_id=graph.conversation.id,
            target_channel=task.target_channel,
            contact_point_id=graph.point.id,
        )

    def _assert_task_and_target(
        self,
        graph: _FollowUpGraph,
        *,
        message: OutboundMessage,
    ) -> None:
        task = graph.task
        if (
            task.status not in _ACTIVE_TASK_STATUSES
            or task.outbound_message_id != message.id
            or task.conversation_id != message.conversation_id
            or task.target_channel != message.channel
            or task.assigned_agent_id != message.automation_agent_id
            or task.scheduled_control_version != message.control_version
            or task.scheduled_automation_version != message.automation_version
            or graph.opportunity.assigned_agent_id != task.assigned_agent_id
            or graph.opportunity.stage in _CLOSED_OPPORTUNITY_STAGES
            or graph.contact.principal_id != graph.conversation.principal_id
            or graph.point.contact_id != graph.contact.id
            or graph.point.verification_status != "verified"
        ):
            raise FollowUpDispatchBlocked("follow_up_authorization_changed")
        expected_kind = {"email": "email", "whatsapp": "phone"}.get(task.target_channel)
        if expected_kind is None or graph.point.kind != expected_kind:
            raise FollowUpDispatchBlocked("follow_up_authorization_changed")
        try:
            target = self._crypto.decrypt(graph.point.ciphertext)
        except ContactCryptoError as exc:
            raise FollowUpDispatchBlocked("follow_up_contact_unavailable") from exc
        if not self._matches_destination(
            channel=task.target_channel,
            target=target,
            destination=message.destination,
        ):
            raise FollowUpDispatchBlocked("follow_up_authorization_changed")

    @staticmethod
    def _matches_destination(
        *,
        channel: str,
        target: str,
        destination: str,
    ) -> bool:
        if channel == "email":
            return target.casefold() == destination.strip().casefold()
        if channel == "whatsapp":
            return target.removeprefix("+") == destination.strip().removeprefix("+")
        return False


@dataclass(frozen=True, slots=True)
class _FollowUpGraph:
    task: FollowUpTask
    opportunity: Opportunity
    conversation: ChatConversation
    contact: Contact
    point: ContactPoint


follow_up_dispatch_authorization_service = FollowUpDispatchAuthorizationService()
