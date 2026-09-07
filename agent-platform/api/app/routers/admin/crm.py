"""Operator-centered collections; semantic commands retain their agent scope."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_admin, require_permission
from app.schemas.channel_inbound import ChannelInboundStatusValue
from app.schemas.conversation_control import ConversationControlMode
from app.schemas.crm import (
    CrmAgentOut,
    CrmAuditOut,
    CrmDeliveryOut,
    CrmFollowUpOut,
    CrmInboundOut,
    CrmInboxOut,
    CrmMeetingOut,
    CrmOpportunityOut,
    CrmPageOut,
    CrmResource,
)
from app.schemas.deliveries import DeliveryStatus
from app.services.admin_agent_access import (
    AgentOperationAccess,
    admin_agent_access_service,
)
from app.services.admin_rbac import AdminPermission, admin_rbac_service
from app.services.audit_read_models import list_audit_records
from app.services.channel_inbound_review import channel_inbound_review_service
from app.services.commercial.follow_up_read_models import follow_up_read_service
from app.services.commercial.meeting_read_models import meeting_read_service
from app.services.commercial.read_models import commercial_read_service
from app.services.operator_inbox import operator_inbox_service
from app.services.outbound_delivery_review import outbound_delivery_review_service

router = APIRouter(tags=["admin-crm"])

_RESOURCE_PERMISSIONS: dict[str, AdminPermission] = {
    "inbox": AdminPermission.CONVERSATIONS_READ,
    "opportunities": AdminPermission.OPPORTUNITIES_READ,
    "meetings": AdminPermission.MEETINGS_READ,
    "follow-ups": AdminPermission.FOLLOW_UPS_READ,
    "deliveries": AdminPermission.DELIVERIES_READ,
    "inbound-jobs": AdminPermission.INBOUND_READ,
    "audit": AdminPermission.AUDIT_READ,
    "automation": AdminPermission.RUNTIME_READ,
}


@dataclass(frozen=True, slots=True)
class CrmReadScope:
    agents: dict[UUID, AgentOperationAccess]

    @property
    def agent_ids(self) -> tuple[UUID, ...]:
        return tuple(self.agents)


def require_crm_scope(permission: AdminPermission):
    async def dependency(
        agent_id: UUID | None = None,
        admin: AdminUser = Depends(require_permission(permission)),
        db: AsyncSession = Depends(get_db),
    ) -> CrmReadScope:
        accessible = await admin_agent_access_service.list_operation_agents(
            db,
            admin_user_id=admin.id,
            role_key=admin.role,
            permission=permission,
        )
        agents = {agent.agent_id: agent for agent in accessible}
        if agent_id is not None:
            if agent_id not in agents:
                raise HTTPException(
                    status_code=403, detail="No tiene acceso a este agente"
                )
            agents = {agent_id: agents[agent_id]}
        return CrmReadScope(agents=agents)

    return dependency


Item = TypeVar("Item", bound=BaseModel)


def _page(
    *,
    items: list[BaseModel],
    total: int,
    owners: dict[UUID, UUID],
    scope: CrmReadScope,
    model: type[Item],
    limit: int,
    offset: int,
) -> CrmPageOut[Item]:
    projected = []
    for item in items:
        owner = scope.agents[owners[UUID(str(item.id))]]
        projected.append(
            model(
                **item.model_dump(),
                owner_agent_id=owner.agent_id,
                owner_agent_name=owner.agent_name,
                capabilities=sorted(owner.capabilities),
            )
        )
    return CrmPageOut[Item](items=projected, total=total, limit=limit, offset=offset)


@router.get("/{resource}/agents", response_model=list[CrmAgentOut])
async def list_crm_agents(
    resource: CrmResource,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CrmAgentOut]:
    permission = _RESOURCE_PERMISSIONS[resource]
    if not await admin_rbac_service.has_permission(
        db, role_key=admin.role, permission=permission
    ):
        raise HTTPException(
            status_code=403, detail="No tiene permisos para esta operación"
        )
    agents = await admin_agent_access_service.list_operation_agents(
        db, admin_user_id=admin.id, role_key=admin.role, permission=permission
    )
    return [
        CrmAgentOut(
            id=agent.agent_id,
            name=agent.agent_name,
            is_active=agent.is_active,
            capabilities=sorted(agent.capabilities),
        )
        for agent in agents
    ]


@router.get("/inbox", response_model=CrmPageOut[CrmInboxOut])
async def list_crm_inbox(
    lifecycle: Literal["active", "history", "all"] = "all",
    admin: AdminUser = Depends(require_admin),
    channel: str | None = Query(default=None, min_length=1, max_length=30),
    control_mode: ConversationControlMode | None = None,
    conversation_status: str | None = Query(
        default=None, alias="status", min_length=1, max_length=30
    ),
    assigned_admin_id: UUID | None = None,
    unassigned_only: bool = False,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(
        require_crm_scope(AdminPermission.CONVERSATIONS_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmInboxOut]:
    if assigned_admin_id is not None and unassigned_only:
        raise HTTPException(
            status_code=422,
            detail="assigned_admin_id and unassigned_only are mutually exclusive",
        )
    result = await operator_inbox_service.list_conversations(
        db,
        agent_id=scope.agent_ids,
        admin_user_id=admin.id,
        lifecycle=lifecycle,
        channel=channel,
        control_mode=control_mode.value if control_mode else None,
        status=conversation_status,
        assigned_admin_id=assigned_admin_id,
        unassigned_only=unassigned_only,
        updated_after=updated_after,
        updated_before=updated_before,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners={item.id: item.routing_agent.id for item in result.items},
        scope=scope,
        model=CrmInboxOut,
        limit=limit,
        offset=offset,
    )


@router.get("/opportunities", response_model=CrmPageOut[CrmOpportunityOut])
async def list_crm_opportunities(
    stage: str | None = Query(default=None, min_length=1, max_length=30),
    assigned_operator_id: UUID | None = None,
    unassigned_only: bool = False,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(
        require_crm_scope(AdminPermission.OPPORTUNITIES_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmOpportunityOut]:
    if assigned_operator_id is not None and unassigned_only:
        raise HTTPException(
            status_code=422,
            detail="assigned_operator_id and unassigned_only are mutually exclusive",
        )
    result = await commercial_read_service.list_opportunities(
        db,
        agent_id=scope.agent_ids,
        stage=stage,
        assigned_operator_id=assigned_operator_id,
        unassigned_only=unassigned_only,
        search=search,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners={item.id: item.assigned_agent.id for item in result.items},
        scope=scope,
        model=CrmOpportunityOut,
        limit=limit,
        offset=offset,
    )


@router.get("/meetings", response_model=CrmPageOut[CrmMeetingOut])
async def list_crm_meetings(
    opportunity_id: UUID | None = None,
    status: str | None = Query(default=None, min_length=1, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(require_crm_scope(AdminPermission.MEETINGS_READ)),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmMeetingOut]:
    result = await meeting_read_service.list_meetings(
        db,
        agent_id=scope.agent_ids,
        opportunity_id=opportunity_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners=result.owner_agent_ids,
        scope=scope,
        model=CrmMeetingOut,
        limit=limit,
        offset=offset,
    )


@router.get("/follow-ups", response_model=CrmPageOut[CrmFollowUpOut])
async def list_crm_follow_ups(
    status: str | None = Query(default=None, min_length=1, max_length=30),
    kind: str | None = Query(default=None, min_length=1, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(require_crm_scope(AdminPermission.FOLLOW_UPS_READ)),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmFollowUpOut]:
    result = await follow_up_read_service.list_tasks(
        db,
        agent_id=scope.agent_ids,
        status=status,
        kind=kind,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners=result.owner_agent_ids,
        scope=scope,
        model=CrmFollowUpOut,
        limit=limit,
        offset=offset,
    )


@router.get("/deliveries", response_model=CrmPageOut[CrmDeliveryOut])
async def list_crm_deliveries(
    channel: str | None = Query(default=None, min_length=1, max_length=30),
    delivery_status: DeliveryStatus | None = Query(default=None, alias="status"),
    conversation_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(require_crm_scope(AdminPermission.DELIVERIES_READ)),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmDeliveryOut]:
    result = await outbound_delivery_review_service.list_deliveries(
        db,
        agent_id=scope.agent_ids,
        channel=channel,
        delivery_status=delivery_status,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners=result.owner_agent_ids,
        scope=scope,
        model=CrmDeliveryOut,
        limit=limit,
        offset=offset,
    )


@router.get("/inbound-jobs", response_model=CrmPageOut[CrmInboundOut])
async def list_crm_inbound(
    status: ChannelInboundStatusValue | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(require_crm_scope(AdminPermission.INBOUND_READ)),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmInboundOut]:
    result = await channel_inbound_review_service.list_jobs(
        db,
        agent_id=scope.agent_ids,
        status=status,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners=result.owner_agent_ids,
        scope=scope,
        model=CrmInboundOut,
        limit=limit,
        offset=offset,
    )


@router.get("/audit", response_model=CrmPageOut[CrmAuditOut])
async def list_crm_audit(
    phone: str | None = None,
    status: str | None = None,
    source_system: str | None = None,
    tool_used: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: CrmReadScope = Depends(require_crm_scope(AdminPermission.AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
) -> CrmPageOut[CrmAuditOut]:
    result = await list_audit_records(
        db,
        agent_ids=scope.agent_ids,
        phone=phone,
        status=status,
        source_system=source_system,
        tool_used=tool_used,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return _page(
        items=result.items,
        total=result.total,
        owners=result.owner_agent_ids,
        scope=scope,
        model=CrmAuditOut,
        limit=limit,
        offset=offset,
    )
