"""Agent-scoped administration API for auditable meeting coordination."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.meeting import (
    MeetingCreateRequest,
    MeetingDetailOut,
    MeetingManualScheduleRequest,
    MeetingMutationOut,
    MeetingPageOut,
    MeetingSlotProposalRequest,
    MeetingSlotSelectionRequest,
    MeetingStatusValue,
    MeetingTransitionRequest,
)
from app.services.admin_rbac import AdminPermission
from app.services.commercial.meeting_read_models import (
    MeetingReadNotFoundError,
    meeting_read_service,
)
from app.services.commercial.meetings import (
    InvalidMeetingCommandError,
    MeetingActor,
    MeetingIdempotencyConflictError,
    MeetingNotFoundError,
    MeetingVersionConflictError,
    ProposedSlot,
    meeting_service,
)
from app.services.commercial.opportunities import (
    OpportunityNotFoundError,
    OpportunityVersionConflictError,
)

router = APIRouter(
    tags=["admin-meetings"],
    dependencies=[Depends(require_agent_permission(AdminPermission.MEETINGS_READ))],
)


@router.get("/", response_model=MeetingPageOut)
async def list_meetings(
    agent_id: uuid.UUID,
    opportunity_id: uuid.UUID | None = None,
    status_filter: MeetingStatusValue | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> MeetingPageOut:
    try:
        page = await meeting_read_service.list_meetings(
            db,
            agent_id=agent_id,
            opportunity_id=opportunity_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except MeetingReadNotFoundError as exc:
        _raise_not_found(exc)
    return MeetingPageOut(
        items=page.items,
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{meeting_id}", response_model=MeetingDetailOut)
async def get_meeting(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MeetingDetailOut:
    try:
        return await meeting_read_service.get_meeting(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
        )
    except MeetingReadNotFoundError as exc:
        _raise_not_found(exc)


@router.post(
    "/",
    response_model=MeetingMutationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_meeting(
    agent_id: uuid.UUID,
    payload: MeetingCreateRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    try:
        result = await meeting_service.create(
            db,
            agent_id=agent_id,
            opportunity_id=payload.opportunity_id,
            conversation_id=payload.conversation_id,
            actor=MeetingActor(admin_id=admin.id),
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_meeting_error(exc)
    return _mutation_out(result, created=result.created)


@router.post("/{meeting_id}/slot-proposals", response_model=MeetingMutationOut)
async def propose_meeting_slots(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingSlotProposalRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    try:
        result = await meeting_service.propose_slots(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor=MeetingActor(admin_id=admin.id),
            expected_version=payload.expected_version,
            slots=[
                ProposedSlot(
                    starts_at=slot.starts_at,
                    ends_at=slot.ends_at,
                    timezone=slot.timezone,
                )
                for slot in payload.slots
            ],
            reason=payload.reason,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_meeting_error(exc)
    return _mutation_out(result)


@router.post("/{meeting_id}/awaiting-response", response_model=MeetingMutationOut)
async def mark_meeting_awaiting_response(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingTransitionRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    return await _operator_transition(
        meeting_service.mark_awaiting_response,
        agent_id=agent_id,
        meeting_id=meeting_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


@router.post("/{meeting_id}/slot-selections", response_model=MeetingMutationOut)
async def select_meeting_slot(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingSlotSelectionRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    try:
        result = await meeting_service.select_slot(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor=MeetingActor(admin_id=admin.id),
            expected_version=payload.expected_version,
            slot_id=payload.slot_id,
            reason=payload.reason,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_meeting_error(exc)
    return _mutation_out(result)


@router.post("/{meeting_id}/manual-schedules", response_model=MeetingMutationOut)
async def schedule_meeting_manually(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingManualScheduleRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    try:
        result = await meeting_service.schedule_manual(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor_admin_id=admin.id,
            expected_version=payload.expected_version,
            expected_opportunity_version=payload.expected_opportunity_version,
            slot_id=payload.slot_id,
            evidence_type=payload.evidence_type,
            evidence_reference=payload.evidence_reference,
            reason=payload.reason,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_meeting_error(exc)
    return _mutation_out(result)


@router.post("/{meeting_id}/reschedule-requests", response_model=MeetingMutationOut)
async def request_meeting_reschedule(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingTransitionRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    return await _operator_transition(
        meeting_service.request_reschedule,
        agent_id=agent_id,
        meeting_id=meeting_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


@router.post("/{meeting_id}/cancellations", response_model=MeetingMutationOut)
async def cancel_meeting(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingTransitionRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    return await _operator_transition(
        meeting_service.cancel,
        agent_id=agent_id,
        meeting_id=meeting_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


@router.post("/{meeting_id}/reviews", response_model=MeetingMutationOut)
async def require_meeting_review(
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingTransitionRequest,
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
        require_agent_permission(AdminPermission.MEETINGS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> MeetingMutationOut:
    return await _operator_transition(
        meeting_service.require_review,
        agent_id=agent_id,
        meeting_id=meeting_id,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        admin=admin,
        db=db,
    )


async def _operator_transition(
    transition,
    *,
    agent_id: uuid.UUID,
    meeting_id: uuid.UUID,
    payload: MeetingTransitionRequest,
    idempotency_key: str,
    correlation_id: str | None,
    admin: AdminUser,
    db: AsyncSession,
) -> MeetingMutationOut:
    try:
        result = await transition(
            db,
            agent_id=agent_id,
            meeting_id=meeting_id,
            actor=MeetingActor(admin_id=admin.id),
            expected_version=payload.expected_version,
            reason=payload.reason,
            correlation_id=_correlation_id(correlation_id),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_meeting_error(exc)
    return _mutation_out(result)


def _mutation_out(result, *, created: bool = False) -> MeetingMutationOut:
    return MeetingMutationOut(
        id=result.meeting.id,
        opportunity_id=result.opportunity.id,
        status=result.meeting.status,
        state_version=result.meeting.state_version,
        proposal_version=result.meeting.proposal_version,
        selected_slot_id=result.meeting.selected_slot_id,
        opportunity_stage=result.opportunity.stage,
        opportunity_control_version=result.opportunity.control_version,
        created=created,
    )


def _correlation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else f"panel-{uuid.uuid4()}"


def _raise_not_found(exc: Exception) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Meeting resource not found",
    ) from exc


def _raise_meeting_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (
            MeetingNotFoundError,
            MeetingReadNotFoundError,
            OpportunityNotFoundError,
        ),
    ):
        _raise_not_found(exc)
    if isinstance(
        exc,
        (
            MeetingVersionConflictError,
            MeetingIdempotencyConflictError,
            OpportunityVersionConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, InvalidMeetingCommandError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc
