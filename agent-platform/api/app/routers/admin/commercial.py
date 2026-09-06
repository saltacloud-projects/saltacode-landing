"""Agent-scoped administration endpoints for commercial opportunities."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.commercial import (
    AuthoritativeQuoteVersionCreateRequest,
    CommercialAutomationPolicyOut,
    CommercialAutomationPolicyUpdateRequest,
    CommercialOperatorOut,
    ConversationLinkMutationOut,
    FollowUpCreateRequest,
    FollowUpMutationOut,
    FollowUpTransitionRequest,
    OpportunityCandidateOut,
    OpportunityConversationLinkRequest,
    OpportunityCreateRequest,
    OpportunityDetailOut,
    OpportunityMutationOut,
    OpportunityPageOut,
    OpportunityReassignmentRequest,
    OpportunityStageTransitionRequest,
    OpportunityStageValue,
    QuoteRequestCreateRequest,
    QuoteRequestMutationOut,
    QuoteVersionMutationOut,
)
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.commercial.follow_ups import (
    FollowUpConsentRequiredError,
    FollowUpIdempotencyConflictError,
    FollowUpNotFoundError,
    FollowUpVersionConflictError,
    InvalidFollowUpCommandError,
    follow_up_service,
)
from app.services.commercial.opportunities import (
    InvalidOpportunityCommandError,
    OpportunityIdempotencyConflictError,
    OpportunityNotFoundError,
    OpportunityVersionConflictError,
    opportunity_service,
)
from app.services.commercial.quotes import (
    InvalidQuoteCommandError,
    QuoteIdempotencyConflictError,
    QuoteRequestNotFoundError,
    QuoteVersionConflictError,
    quote_service,
)
from app.services.commercial.read_models import (
    CommercialReadNotFoundError,
    commercial_read_service,
)

router = APIRouter(
    tags=["admin-commercial"],
    dependencies=[
        Depends(require_agent_permission(AdminPermission.OPPORTUNITIES_READ))
    ],
)


@router.get("/automation-policy", response_model=CommercialAutomationPolicyOut)
async def get_commercial_automation_policy(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CommercialAutomationPolicyOut:
    policy = await follow_up_service.get_policy(db, agent_id=agent_id)
    return CommercialAutomationPolicyOut.model_validate(policy, from_attributes=True)


@router.put("/automation-policy", response_model=CommercialAutomationPolicyOut)
async def update_commercial_automation_policy(
    agent_id: uuid.UUID,
    payload: CommercialAutomationPolicyUpdateRequest,
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> CommercialAutomationPolicyOut:
    try:
        policy = await follow_up_service.configure_policy(
            db,
            agent_id=agent_id,
            actor_admin_id=admin.id,
            expected_version=payload.expected_version,
            is_enabled=payload.is_enabled,
            allowed_kinds=payload.allowed_kinds,
            timezone=payload.timezone,
            quiet_hours_start=payload.quiet_hours_start,
            quiet_hours_end=payload.quiet_hours_end,
            min_interval_seconds=payload.min_interval_seconds,
            max_attempts=payload.max_attempts,
            max_daily_tasks=payload.max_daily_tasks,
            max_pending_tasks=payload.max_pending_tasks,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return CommercialAutomationPolicyOut.model_validate(policy, from_attributes=True)


@router.get("/", response_model=OpportunityPageOut)
async def list_opportunities(
    agent_id: uuid.UUID,
    stage_filter: OpportunityStageValue | None = Query(default=None, alias="stage"),
    assigned_operator_id: uuid.UUID | None = None,
    unassigned_only: bool = False,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> OpportunityPageOut:
    if assigned_operator_id is not None and unassigned_only:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assigned_operator_id and unassigned_only are mutually exclusive",
        )
    try:
        page = await commercial_read_service.list_opportunities(
            db,
            agent_id=agent_id,
            stage=stage_filter,
            assigned_operator_id=assigned_operator_id,
            unassigned_only=unassigned_only,
            search=search,
            limit=limit,
            offset=offset,
        )
    except CommercialReadNotFoundError as exc:
        _raise_not_found(exc)
    return OpportunityPageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/candidates", response_model=list[OpportunityCandidateOut])
async def list_opportunity_candidates(
    agent_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[OpportunityCandidateOut]:
    try:
        return await commercial_read_service.list_candidates(
            db,
            agent_id=agent_id,
            limit=limit,
        )
    except CommercialReadNotFoundError as exc:
        _raise_not_found(exc)


@router.get("/operators", response_model=list[CommercialOperatorOut])
async def list_opportunity_operators(
    agent_id: uuid.UUID,
    _admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> list[CommercialOperatorOut]:
    try:
        return await commercial_read_service.list_operators(db, agent_id=agent_id)
    except CommercialReadNotFoundError as exc:
        _raise_not_found(exc)


@router.get("/{opportunity_id}", response_model=OpportunityDetailOut)
async def get_opportunity(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetailOut:
    try:
        return await commercial_read_service.get_opportunity(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
        )
    except CommercialReadNotFoundError as exc:
        _raise_not_found(exc)


@router.post(
    "/",
    response_model=OpportunityMutationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_opportunity(
    agent_id: uuid.UUID,
    payload: OpportunityCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> OpportunityMutationOut:
    try:
        await _assert_operator_can_manage_agent(
            db,
            agent_id=agent_id,
            operator_id=payload.assigned_operator_id,
        )
        result = await opportunity_service.create(
            db,
            contact_id=payload.contact_id,
            source_conversation_id=payload.source_conversation_id,
            created_by_agent_id=agent_id,
            assigned_agent_id=agent_id,
            assigned_operator_id=payload.assigned_operator_id,
            title=payload.title,
            summary=payload.summary,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return _opportunity_mutation(result.opportunity, created=result.created)


@router.post(
    "/{opportunity_id}/stage-transitions",
    response_model=OpportunityMutationOut,
)
async def transition_opportunity_stage(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: OpportunityStageTransitionRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> OpportunityMutationOut:
    try:
        await commercial_read_service.assert_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
        )
        result = await opportunity_service.transition_stage(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            target_stage=payload.target_stage,
            expected_version=payload.expected_version,
            reason=payload.reason,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return _opportunity_mutation(result.opportunity, created=result.created)


@router.post(
    "/{opportunity_id}/reassignments",
    response_model=OpportunityMutationOut,
)
async def reassign_opportunity(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: OpportunityReassignmentRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> OpportunityMutationOut:
    try:
        await commercial_read_service.assert_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
        )
        if not await admin_agent_access_service.has_permission(
            db,
            admin_user_id=admin.id,
            role_key=admin.role,
            agent_id=payload.assigned_agent_id,
            permission=AdminPermission.OPPORTUNITIES_MANAGE,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene acceso comercial al agente de destino",
            )
        await _assert_operator_can_manage_agent(
            db,
            agent_id=payload.assigned_agent_id,
            operator_id=payload.assigned_operator_id,
        )
        result = await opportunity_service.reassign(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            assigned_agent_id=payload.assigned_agent_id,
            assigned_operator_id=payload.assigned_operator_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return _opportunity_mutation(result.opportunity, created=result.created)


@router.post(
    "/{opportunity_id}/conversation-links",
    response_model=ConversationLinkMutationOut,
    status_code=status.HTTP_201_CREATED,
)
async def link_opportunity_conversation(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: OpportunityConversationLinkRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> ConversationLinkMutationOut:
    try:
        await commercial_read_service.assert_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
        )
        result = await opportunity_service.link_conversation(
            db,
            opportunity_id=opportunity_id,
            conversation_id=payload.conversation_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return ConversationLinkMutationOut(
        id=result.link.id,
        conversation_id=result.link.conversation_id,
        created=result.created,
    )


@router.post(
    "/{opportunity_id}/follow-ups",
    response_model=FollowUpMutationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_follow_up(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: FollowUpCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> FollowUpMutationOut:
    try:
        await commercial_read_service.assert_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
        )
        result = await follow_up_service.schedule(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            contact_point_id=payload.contact_point_id,
            conversation_id=payload.conversation_id,
            target_channel=payload.target_channel,
            quote_version_id=payload.quote_version_id,
            kind=payload.kind,
            due_at=payload.due_at,
            note=payload.note,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return FollowUpMutationOut(
        id=result.task.id,
        status=result.task.status,
        state_version=result.task.state_version,
        created=result.created,
    )


@router.post(
    "/{opportunity_id}/follow-ups/{task_id}/transitions",
    response_model=FollowUpMutationOut,
)
async def transition_follow_up(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: FollowUpTransitionRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> FollowUpMutationOut:
    try:
        await commercial_read_service.assert_follow_up_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
            task_id=task_id,
        )
        task = await follow_up_service.transition(
            db,
            task_id=task_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            target_status=payload.target_status,
            expected_version=payload.expected_version,
            safe_code=payload.safe_code,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=(
                idempotency_key
                or f"follow-up-transition:{task_id}:{payload.expected_version}:"
                f"{payload.target_status}"
            ),
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return FollowUpMutationOut(
        id=task.id,
        status=task.status,
        state_version=task.state_version,
        created=False,
    )


@router.post(
    "/{opportunity_id}/quote-requests",
    response_model=QuoteRequestMutationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_quote_request(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: QuoteRequestCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.OPPORTUNITIES_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> QuoteRequestMutationOut:
    try:
        await commercial_read_service.assert_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
        )
        result = await quote_service.request(
            db,
            opportunity_id=opportunity_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            requirements=payload.requirements,
            status=payload.status,
            failure_code=payload.failure_code,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return QuoteRequestMutationOut(
        id=result.request.id,
        status=result.request.status,
        state_version=result.request.state_version,
        failure_code=result.request.failure_code,
        created=result.created,
    )


@router.post(
    "/{opportunity_id}/quote-requests/{quote_request_id}/authoritative-versions",
    response_model=QuoteVersionMutationOut,
)
async def create_authoritative_quote_version(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    quote_request_id: uuid.UUID,
    payload: AuthoritativeQuoteVersionCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    correlation_id: str | None = Header(
        default=None,
        alias="X-Correlation-ID",
        max_length=120,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.QUOTES_APPROVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> QuoteVersionMutationOut:
    try:
        await commercial_read_service.assert_quote_request_owned(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
            quote_request_id=quote_request_id,
        )
        result = await quote_service.issue_authoritative_version(
            db,
            quote_request_id=quote_request_id,
            actor_agent_id=agent_id,
            actor_operator_id=admin.id,
            expected_version=payload.expected_version,
            authority_name=payload.authority_name,
            authority_version=payload.authority_version,
            external_reference=payload.external_reference,
            content_hash=payload.content_hash,
            issued_at=payload.issued_at,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_commercial_error(exc)
    return QuoteVersionMutationOut(
        quote_request_id=result.request.id,
        quote_request_status=result.request.status,
        quote_request_state_version=result.request.state_version,
        quote_version_id=result.version.id,
        version=result.version.version,
        created=result.created,
    )


def _opportunity_mutation(opportunity, *, created: bool) -> OpportunityMutationOut:
    return OpportunityMutationOut(
        id=opportunity.id,
        stage=opportunity.stage,
        control_version=opportunity.control_version,
        assigned_agent_id=opportunity.assigned_agent_id,
        assigned_operator_id=opportunity.assigned_operator_id,
        created=created,
    )


def _correlation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else f"panel-{uuid.uuid4()}"


async def _assert_operator_can_manage_agent(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    operator_id: uuid.UUID | None,
) -> None:
    if operator_id is None:
        return
    operator = await db.get(AdminUser, operator_id)
    if (
        operator is None
        or not operator.is_active
        or not await admin_agent_access_service.has_permission(
            db,
            admin_user_id=operator.id,
            role_key=operator.role,
            agent_id=agent_id,
            permission=AdminPermission.OPPORTUNITIES_MANAGE,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El operador asignado no puede gestionar el agente",
        )


def _raise_not_found(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Commercial resource not found",
    ) from exc


def _raise_commercial_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (
            CommercialReadNotFoundError,
            OpportunityNotFoundError,
            FollowUpNotFoundError,
            QuoteRequestNotFoundError,
        ),
    ):
        _raise_not_found(exc)
    if isinstance(
        exc,
        (
            OpportunityVersionConflictError,
            OpportunityIdempotencyConflictError,
            FollowUpVersionConflictError,
            FollowUpIdempotencyConflictError,
            FollowUpConsentRequiredError,
            QuoteVersionConflictError,
            QuoteIdempotencyConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(
        exc,
        (
            InvalidOpportunityCommandError,
            InvalidFollowUpCommandError,
            InvalidQuoteCommandError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc
