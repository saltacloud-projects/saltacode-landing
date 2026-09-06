"""Agent-scoped administration API for deterministic handoff routes."""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.models.agent_handoff_route import AgentHandoffRoute
from app.routers.admin.auth import require_agent_permission
from app.schemas.agent_handoff_route import (
    AgentHandoffRouteCreateRequest,
    AgentHandoffRouteDeactivateRequest,
    AgentHandoffRouteOut,
    AgentHandoffRouteUpdateRequest,
)
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission
from app.services.agent_handoff_routes import (
    AgentHandoffRouteConflictError,
    AgentHandoffRouteIdempotencyError,
    AgentHandoffRouteNotFoundError,
    AgentHandoffRouteValidationError,
    AgentHandoffRouteVersionConflictError,
    agent_handoff_route_service,
)

router = APIRouter(tags=["admin-agent-handoff-routes"])


@router.get(
    "/",
    response_model=list[AgentHandoffRouteOut],
)
async def list_handoff_routes(
    agent_id: uuid.UUID,
    _admin: AdminUser = Depends(require_agent_permission(AdminPermission.RUNTIME_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[AgentHandoffRouteOut]:
    routes = await agent_handoff_route_service.list_routes(
        db,
        source_agent_id=agent_id,
    )
    return [_out(route) for route in routes]


@router.get(
    "/{route_id}",
    response_model=AgentHandoffRouteOut,
)
async def get_handoff_route(
    agent_id: uuid.UUID,
    route_id: uuid.UUID,
    _admin: AdminUser = Depends(require_agent_permission(AdminPermission.RUNTIME_READ)),
    db: AsyncSession = Depends(get_db),
) -> AgentHandoffRouteOut:
    try:
        route = await agent_handoff_route_service.get_route(
            db,
            source_agent_id=agent_id,
            route_id=route_id,
        )
    except AgentHandoffRouteNotFoundError as exc:
        _raise_handoff_error(exc)
    return _out(route)


@router.post(
    "/",
    response_model=AgentHandoffRouteOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_handoff_route(
    agent_id: uuid.UUID,
    payload: AgentHandoffRouteCreateRequest,
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.RUNTIME_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> AgentHandoffRouteOut:
    await _require_target_manage(
        db,
        admin=admin,
        target_agent_id=payload.target_agent_id,
    )
    try:
        result = await agent_handoff_route_service.create_route(
            db,
            source_agent_id=agent_id,
            target_agent_id=payload.target_agent_id,
            trigger=payload.trigger,
            is_active=payload.is_active,
            actor_admin_id=admin.id,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _raise_handoff_error(exc)
    return _out(result.route)


@router.patch(
    "/{route_id}",
    response_model=AgentHandoffRouteOut,
)
async def update_handoff_route(
    agent_id: uuid.UUID,
    route_id: uuid.UUID,
    payload: AgentHandoffRouteUpdateRequest,
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.RUNTIME_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> AgentHandoffRouteOut:
    try:
        current = await agent_handoff_route_service.get_route(
            db,
            source_agent_id=agent_id,
            route_id=route_id,
        )
        await _require_target_manage(
            db,
            admin=admin,
            target_agent_id=payload.target_agent_id or current.target_agent_id,
        )
        result = await agent_handoff_route_service.update_route(
            db,
            source_agent_id=agent_id,
            route_id=route_id,
            target_agent_id=payload.target_agent_id,
            is_active=payload.is_active,
            actor_admin_id=admin.id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _raise_handoff_error(exc)
    return _out(result.route)


@router.post(
    "/{route_id}/deactivate",
    response_model=AgentHandoffRouteOut,
)
async def deactivate_handoff_route(
    agent_id: uuid.UUID,
    route_id: uuid.UUID,
    payload: AgentHandoffRouteDeactivateRequest,
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.RUNTIME_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> AgentHandoffRouteOut:
    try:
        current = await agent_handoff_route_service.get_route(
            db,
            source_agent_id=agent_id,
            route_id=route_id,
        )
        await _require_target_manage(
            db,
            admin=admin,
            target_agent_id=current.target_agent_id,
        )
        result = await agent_handoff_route_service.deactivate_route(
            db,
            source_agent_id=agent_id,
            route_id=route_id,
            actor_admin_id=admin.id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        _raise_handoff_error(exc)
    return _out(result.route)


async def _require_target_manage(
    db: AsyncSession,
    *,
    admin: AdminUser,
    target_agent_id: uuid.UUID,
) -> None:
    allowed = await admin_agent_access_service.has_permission(
        db,
        admin_user_id=admin.id,
        role_key=admin.role,
        agent_id=target_agent_id,
        permission=AdminPermission.RUNTIME_MANAGE,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene acceso al agente destino",
        )


def _out(route: AgentHandoffRoute) -> AgentHandoffRouteOut:
    return AgentHandoffRouteOut(
        id=route.id,
        source_agent_id=route.source_agent_id,
        target_agent_id=route.target_agent_id,
        trigger=route.trigger,
        is_active=route.is_active,
        control_version=route.control_version,
        created_by_admin_id=route.created_by_admin_id,
        updated_by_admin_id=route.updated_by_admin_id,
        created_at=route.created_at,
        updated_at=route.updated_at,
    )


def _raise_handoff_error(exc: Exception) -> NoReturn:
    if isinstance(exc, AgentHandoffRouteNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handoff route not found",
        ) from exc
    if isinstance(
        exc,
        (
            AgentHandoffRouteConflictError,
            AgentHandoffRouteIdempotencyError,
            AgentHandoffRouteVersionConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, AgentHandoffRouteValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc
