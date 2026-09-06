"""Agent-scoped read models for the commercial workspace."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.contact import Contact, ContactPoint
from app.models.opportunity import (
    FollowUpTask,
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.platform import ChatConversation, Principal
from app.models.quote import QuoteRequest, QuoteVersion
from app.schemas.commercial import (
    CommercialAgentOut,
    CommercialContactOut,
    CommercialOperatorOut,
    ContactPointOut,
    ConversationCandidateOut,
    FollowUpTaskOut,
    OpportunityCandidateOut,
    OpportunityConversationOut,
    OpportunityDetailOut,
    OpportunityOwnershipEventOut,
    OpportunityStageEventOut,
    OpportunitySummaryOut,
    QuoteRequestOut,
    QuoteVersionOut,
)
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.commercial.consents import (
    ConsentPurpose,
    ConsentService,
    ConsentServiceError,
)
from app.services.commercial.contacts import ContactServiceError


class CommercialReadNotFoundError(Exception):
    """The requested agent-owned resource is absent or outside its scope."""


@dataclass(frozen=True, slots=True)
class OpportunityPage:
    items: list[OpportunitySummaryOut]
    total: int


class CommercialReadService:
    """Build privacy-minimized projections without decrypting contact data."""

    def __init__(self, *, consents: ConsentService | None = None) -> None:
        self._consents = consents or ConsentService()

    async def list_opportunities(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        stage: str | None = None,
        assigned_operator_id: uuid.UUID | None = None,
        unassigned_only: bool = False,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> OpportunityPage:
        await self._assert_agent_exists(db, agent_id)
        statement = self._summary_statement(agent_id)
        if stage:
            statement = statement.where(Opportunity.stage == stage)
        if assigned_operator_id:
            statement = statement.where(
                Opportunity.assigned_operator_id == assigned_operator_id
            )
        if unassigned_only:
            statement = statement.where(Opportunity.assigned_operator_id.is_(None))
        normalized_search = (search or "").strip()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            statement = statement.where(
                or_(
                    Opportunity.title.ilike(pattern),
                    Contact.company_name.ilike(pattern),
                    Principal.display_name.ilike(pattern),
                )
            )
        total = int(
            (
                await db.execute(select(func.count()).select_from(statement.subquery()))
            ).scalar_one()
        )
        rows = (
            await db.execute(
                statement.order_by(Opportunity.updated_at.desc(), Opportunity.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return OpportunityPage(
            items=[self._summary_out(row) for row in rows],
            total=total,
        )

    async def get_opportunity(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        opportunity_id: uuid.UUID,
    ) -> OpportunityDetailOut:
        row = (
            await db.execute(
                self._summary_statement(agent_id).where(
                    Opportunity.id == opportunity_id
                )
            )
        ).one_or_none()
        if row is None:
            raise CommercialReadNotFoundError("opportunity not found")
        opportunity, contact, principal, *_ = row
        summary = self._summary_out(row)
        summary.contact.contact_points = await self._contact_points(
            db,
            contact=contact,
            consent_agent_id=opportunity.created_by_agent_id,
        )

        links = list(
            (
                await db.execute(
                    select(OpportunityConversation, ChatConversation)
                    .outerjoin(
                        ChatConversation,
                        ChatConversation.id == OpportunityConversation.conversation_id,
                    )
                    .where(OpportunityConversation.opportunity_id == opportunity.id)
                    .order_by(
                        OpportunityConversation.created_at,
                        OpportunityConversation.id,
                    )
                )
            ).all()
        )
        linked_ids = {
            link.conversation_id
            for link, _conversation in links
            if link.conversation_id
        }
        available_conversations = list(
            (
                await db.execute(
                    select(ChatConversation)
                    .where(
                        ChatConversation.principal_id == contact.principal_id,
                        ChatConversation.id.not_in(linked_ids) if linked_ids else True,
                    )
                    .order_by(ChatConversation.updated_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        stage_events = list(
            (
                await db.execute(
                    select(OpportunityStageEvent)
                    .where(OpportunityStageEvent.opportunity_id == opportunity.id)
                    .order_by(OpportunityStageEvent.control_version)
                )
            )
            .scalars()
            .all()
        )
        ownership_events = list(
            (
                await db.execute(
                    select(OpportunityOwnershipEvent)
                    .where(OpportunityOwnershipEvent.opportunity_id == opportunity.id)
                    .order_by(OpportunityOwnershipEvent.control_version)
                )
            )
            .scalars()
            .all()
        )
        follow_ups = list(
            (
                await db.execute(
                    select(FollowUpTask)
                    .where(FollowUpTask.opportunity_id == opportunity.id)
                    .order_by(FollowUpTask.due_at, FollowUpTask.id)
                )
            )
            .scalars()
            .all()
        )
        quote_requests = list(
            (
                await db.execute(
                    select(QuoteRequest)
                    .where(QuoteRequest.opportunity_id == opportunity.id)
                    .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id)
                )
            )
            .scalars()
            .all()
        )
        versions_by_request: dict[uuid.UUID, list[QuoteVersion]] = {}
        if quote_requests:
            versions = list(
                (
                    await db.execute(
                        select(QuoteVersion)
                        .where(
                            QuoteVersion.quote_request_id.in_(
                                [request.id for request in quote_requests]
                            )
                        )
                        .order_by(
                            QuoteVersion.quote_request_id,
                            QuoteVersion.version,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for version in versions:
                versions_by_request.setdefault(version.quote_request_id, []).append(
                    version
                )

        return OpportunityDetailOut(
            **summary.model_dump(),
            available_conversations=[
                ConversationCandidateOut(
                    id=conversation.id,
                    agent_id=conversation.agent_id,
                    channel=conversation.channel,
                    route_key=conversation.route_key,
                    status=conversation.status,
                    updated_at=conversation.updated_at,
                )
                for conversation in available_conversations
            ],
            conversations=[
                OpportunityConversationOut(
                    id=link.id,
                    conversation_id=link.conversation_id,
                    channel=conversation.channel if conversation else None,
                    route_key=conversation.route_key if conversation else None,
                    status=conversation.status if conversation else None,
                    linked_at=link.created_at,
                )
                for link, conversation in links
            ],
            stage_events=[
                OpportunityStageEventOut(
                    id=event.id,
                    event_type=event.event_type,
                    from_stage=event.from_stage,
                    to_stage=event.to_stage,
                    control_version=event.control_version,
                    reason=event.reason,
                    created_at=event.created_at,
                )
                for event in stage_events
            ],
            ownership_events=[
                OpportunityOwnershipEventOut(
                    id=event.id,
                    event_type=event.event_type,
                    from_agent_id=event.from_agent_id,
                    to_agent_id=event.to_agent_id,
                    from_operator_id=event.from_operator_id,
                    to_operator_id=event.to_operator_id,
                    control_version=event.control_version,
                    reason=event.reason,
                    created_at=event.created_at,
                )
                for event in ownership_events
            ],
            follow_ups=[self._follow_up_out(task) for task in follow_ups],
            quote_requests=[
                self._quote_request_out(
                    request,
                    versions_by_request.get(request.id, []),
                )
                for request in quote_requests
            ],
        )

    async def list_candidates(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        limit: int = 100,
    ) -> list[OpportunityCandidateOut]:
        await self._assert_agent_exists(db, agent_id)
        rows = (
            await db.execute(
                select(Contact, Principal, ChatConversation)
                .join(Principal, Principal.id == Contact.principal_id)
                .join(
                    ChatConversation,
                    ChatConversation.principal_id == Contact.principal_id,
                )
                .where(
                    ChatConversation.agent_id == agent_id,
                    Contact.status != "archived",
                )
                .order_by(ChatConversation.updated_at.desc())
                .limit(limit)
            )
        ).all()
        result: list[OpportunityCandidateOut] = []
        for contact, principal, conversation in rows:
            result.append(
                OpportunityCandidateOut(
                    contact=CommercialContactOut(
                        id=contact.id,
                        principal_id=contact.principal_id,
                        display_name=principal.display_name,
                        company_name=contact.company_name,
                        job_title=contact.job_title,
                        status=contact.status,
                        contact_points=await self._contact_points(
                            db,
                            contact=contact,
                            consent_agent_id=agent_id,
                        ),
                    ),
                    conversation_id=conversation.id,
                    channel=conversation.channel,
                    route_key=conversation.route_key,
                    conversation_status=conversation.status,
                    conversation_updated_at=conversation.updated_at,
                )
            )
        return result

    async def list_operators(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
    ) -> list[CommercialOperatorOut]:
        await self._assert_agent_exists(db, agent_id)
        operators = list(
            (
                await db.execute(
                    select(AdminUser)
                    .where(AdminUser.is_active.is_(True))
                    .order_by(AdminUser.name, AdminUser.email)
                )
            )
            .scalars()
            .all()
        )
        result: list[CommercialOperatorOut] = []
        for operator in operators:
            if await admin_agent_access_service.has_permission(
                db,
                admin_user_id=operator.id,
                role_key=operator.role,
                agent_id=agent_id,
                permission=AdminPermission.OPPORTUNITIES_MANAGE,
            ):
                result.append(
                    CommercialOperatorOut(
                        id=operator.id,
                        name=operator.name,
                        email=operator.email,
                    )
                )
        return result

    async def assert_owned(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        opportunity_id: uuid.UUID,
    ) -> None:
        owned_id = (
            await db.execute(
                select(Opportunity.id).where(
                    Opportunity.id == opportunity_id,
                    Opportunity.assigned_agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if owned_id is None:
            raise CommercialReadNotFoundError("opportunity not found")

    async def assert_follow_up_owned(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> None:
        task = (
            await db.execute(
                select(FollowUpTask.id)
                .join(Opportunity, Opportunity.id == FollowUpTask.opportunity_id)
                .where(
                    FollowUpTask.id == task_id,
                    FollowUpTask.opportunity_id == opportunity_id,
                    Opportunity.assigned_agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise CommercialReadNotFoundError("follow-up task not found")

    async def assert_quote_request_owned(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        quote_request_id: uuid.UUID,
    ) -> None:
        request = (
            await db.execute(
                select(QuoteRequest.id)
                .join(Opportunity, Opportunity.id == QuoteRequest.opportunity_id)
                .where(
                    QuoteRequest.id == quote_request_id,
                    QuoteRequest.opportunity_id == opportunity_id,
                    Opportunity.assigned_agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise CommercialReadNotFoundError("quote request not found")

    @staticmethod
    def _summary_statement(agent_id: uuid.UUID) -> Select:
        assigned_agent = aliased(AgentProfile, name="commercial_assigned_agent")
        assigned_operator = aliased(AdminUser, name="commercial_assigned_operator")
        linked_count = (
            select(func.count(OpportunityConversation.id))
            .where(OpportunityConversation.opportunity_id == Opportunity.id)
            .correlate(Opportunity)
            .scalar_subquery()
        )
        pending_follow_up_count = (
            select(func.count(FollowUpTask.id))
            .where(
                FollowUpTask.opportunity_id == Opportunity.id,
                FollowUpTask.status.not_in(["completed", "cancelled"]),
            )
            .correlate(Opportunity)
            .scalar_subquery()
        )
        latest_quote_status = (
            select(QuoteRequest.status)
            .where(QuoteRequest.opportunity_id == Opportunity.id)
            .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc())
            .limit(1)
            .correlate(Opportunity)
            .scalar_subquery()
        )
        return (
            select(
                Opportunity,
                Contact,
                Principal,
                assigned_agent,
                assigned_operator,
                linked_count,
                pending_follow_up_count,
                latest_quote_status,
            )
            .join(Contact, Contact.id == Opportunity.contact_id)
            .join(Principal, Principal.id == Contact.principal_id)
            .join(assigned_agent, assigned_agent.id == Opportunity.assigned_agent_id)
            .outerjoin(
                assigned_operator,
                assigned_operator.id == Opportunity.assigned_operator_id,
            )
            .where(Opportunity.assigned_agent_id == agent_id)
        )

    @staticmethod
    def _summary_out(row) -> OpportunitySummaryOut:
        (
            opportunity,
            contact,
            principal,
            assigned_agent,
            assigned_operator,
            linked_count,
            pending_follow_up_count,
            latest_quote_status,
        ) = row
        return OpportunitySummaryOut(
            id=opportunity.id,
            title=opportunity.title,
            summary=opportunity.summary,
            stage=opportunity.stage,
            control_version=opportunity.control_version,
            contact=CommercialContactOut(
                id=contact.id,
                principal_id=contact.principal_id,
                display_name=principal.display_name,
                company_name=contact.company_name,
                job_title=contact.job_title,
                status=contact.status,
            ),
            assigned_agent=CommercialAgentOut(
                id=assigned_agent.id,
                name=assigned_agent.name,
            ),
            assigned_operator=(
                CommercialOperatorOut(
                    id=assigned_operator.id,
                    name=assigned_operator.name,
                    email=assigned_operator.email,
                )
                if assigned_operator
                else None
            ),
            linked_conversation_count=int(linked_count or 0),
            pending_follow_up_count=int(pending_follow_up_count or 0),
            latest_quote_status=latest_quote_status,
            created_at=opportunity.created_at,
            updated_at=opportunity.updated_at,
            closed_at=opportunity.closed_at,
        )

    async def _contact_points(
        self,
        db: AsyncSession,
        *,
        contact: Contact,
        consent_agent_id: uuid.UUID,
    ) -> list[ContactPointOut]:
        points = list(
            (
                await db.execute(
                    select(ContactPoint)
                    .where(ContactPoint.contact_id == contact.id)
                    .order_by(ContactPoint.kind, ContactPoint.id)
                )
            )
            .scalars()
            .all()
        )
        result: list[ContactPointOut] = []
        for point in points:
            follow_up_allowed = await self._consent_allowed(
                db,
                contact=contact,
                point=point,
                agent_id=consent_agent_id,
                purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            )
            quote_delivery_allowed = await self._consent_allowed(
                db,
                contact=contact,
                point=point,
                agent_id=consent_agent_id,
                purpose=ConsentPurpose.QUOTE_DELIVERY,
            )
            result.append(
                ContactPointOut(
                    id=point.id,
                    kind=point.kind,
                    masked_value=point.masked_value,
                    verification_status=point.verification_status,
                    commercial_follow_up_allowed=follow_up_allowed,
                    quote_delivery_allowed=quote_delivery_allowed,
                )
            )
        return result

    async def _consent_allowed(
        self,
        db: AsyncSession,
        *,
        contact: Contact,
        point: ContactPoint,
        agent_id: uuid.UUID,
        purpose: ConsentPurpose,
    ) -> bool:
        try:
            effective = await self._consents.effective(
                db,
                agent_id=agent_id,
                principal_id=contact.principal_id,
                purpose=purpose,
                contact_point_id=point.id,
            )
        except (ConsentServiceError, ContactServiceError):
            return False
        return effective.granted

    @staticmethod
    def _follow_up_out(task: FollowUpTask) -> FollowUpTaskOut:
        return FollowUpTaskOut(
            id=task.id,
            contact_point_id=task.contact_point_id,
            consent_record_id=task.consent_record_id,
            assigned_agent_id=task.assigned_agent_id,
            assigned_operator_id=task.assigned_operator_id,
            kind=task.kind,
            status=task.status,
            state_version=task.state_version,
            due_at=task.due_at,
            note=task.note,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    @staticmethod
    def _quote_request_out(
        request: QuoteRequest,
        versions: list[QuoteVersion],
    ) -> QuoteRequestOut:
        return QuoteRequestOut(
            id=request.id,
            status=request.status,
            state_version=request.state_version,
            requirements=request.requirements_json,
            failure_code=request.failure_code,
            created_at=request.created_at,
            updated_at=request.updated_at,
            versions=[
                QuoteVersionOut(
                    id=version.id,
                    version=version.version,
                    status=version.status,
                    authority_name=version.authority_name,
                    authority_version=version.authority_version,
                    external_reference=version.external_reference,
                    content_hash=version.content_hash,
                    issued_at=version.issued_at,
                    recorded_at=version.created_at,
                )
                for version in versions
            ],
        )

    @staticmethod
    async def _assert_agent_exists(
        db: AsyncSession,
        agent_id: uuid.UUID,
    ) -> None:
        exists = (
            await db.execute(select(AgentProfile.id).where(AgentProfile.id == agent_id))
        ).scalar_one_or_none()
        if exists is None:
            raise CommercialReadNotFoundError("agent not found")


commercial_read_service = CommercialReadService()
