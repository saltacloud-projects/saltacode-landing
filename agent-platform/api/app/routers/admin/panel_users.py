"""Administración de cuentas y roles del panel web."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.dependencies import get_db
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.routers.admin.auth import require_admin, require_permission
from app.schemas.admin import (
    AdminAgentGrantCollectionOut,
    AdminAgentGrantOut,
    AdminAgentGrantUpdate,
    AdminAgentOptionOut,
    AdminRoleOut,
    AdminUserOut,
    PanelUserCreate,
    PanelUserPasswordReset,
    PanelUserUpdate,
)
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission, admin_rbac_service

router = APIRouter(
    tags=["admin-panel-users"],
    dependencies=[Depends(require_permission(AdminPermission.PANEL_USERS_MANAGE))],
)


async def _role_or_422(db: AsyncSession, key: str) -> AdminRole:
    role = (
        await db.execute(
            select(AdminRole).where(AdminRole.key == key, AdminRole.is_active == True)  # noqa: E712
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=422, detail="Rol inexistente o inactivo")
    return role


async def _user_or_404(db: AsyncSession, user_id: str) -> AdminUser:
    try:
        uid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="Usuario del panel no encontrado"
        ) from exc
    user = await db.get(AdminUser, uid)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario del panel no encontrado")
    return user


async def _agent_or_404(db: AsyncSession, agent_id: str) -> AgentProfile:
    try:
        uid = uuid.UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agente no encontrado") from exc
    agent = await db.get(AgentProfile, uid)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    return agent


async def _role_has_global_access(db: AsyncSession, key: str) -> bool:
    permissions = (
        await db.execute(select(AdminRole.permissions).where(AdminRole.key == key))
    ).scalar_one_or_none()
    return isinstance(permissions, list) and "*" in permissions


async def _out(db: AsyncSession, user: AdminUser) -> AdminUserOut:
    permissions = await admin_rbac_service.permissions_for_role(db, user.role)
    return AdminUserOut.from_orm_model(user, list(permissions))


def _grant_out(grant: AdminAgentGrant, agent: AgentProfile) -> AdminAgentGrantOut:
    return AdminAgentGrantOut(
        id=str(grant.id),
        agent_id=str(agent.id),
        agent_name=agent.name,
        agent_slug=agent.slug,
        permissions=list(grant.permissions),
        is_active=grant.is_active,
        created_at=grant.created_at,
        updated_at=grant.updated_at,
    )


@router.get("/roles", response_model=list[AdminRoleOut])
async def list_roles(db: AsyncSession = Depends(get_db)):
    roles = (
        (await db.execute(select(AdminRole).order_by(AdminRole.name))).scalars().all()
    )
    return [
        AdminRoleOut(
            key=role.key,
            name=role.name,
            description=role.description,
            permissions=list(role.permissions or []),
            is_active=role.is_active,
            is_system=role.is_system,
        )
        for role in roles
    ]


@router.get("/", response_model=list[AdminUserOut])
async def list_panel_users(db: AsyncSession = Depends(get_db)):
    users = (
        (await db.execute(select(AdminUser).order_by(AdminUser.name, AdminUser.email)))
        .scalars()
        .all()
    )
    return [await _out(db, user) for user in users]


@router.get(
    "/{user_id}/agent-grants",
    response_model=AdminAgentGrantCollectionOut,
)
async def list_panel_user_agent_grants(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    user = await _user_or_404(db, user_id)
    agents = (
        (
            await db.execute(
                select(AgentProfile).order_by(AgentProfile.name, AgentProfile.slug)
            )
        )
        .scalars()
        .all()
    )
    grants = await admin_agent_access_service.list_grants(
        db,
        admin_user_id=user.id,
    )
    available_permissions = await admin_agent_access_service.grantable_permissions(
        db,
        role_key=user.role,
    )
    return AdminAgentGrantCollectionOut(
        user_id=str(user.id),
        available_permissions=available_permissions,
        agents=[
            AdminAgentOptionOut(
                id=str(agent.id),
                name=agent.name,
                slug=agent.slug,
                is_active=agent.is_active,
            )
            for agent in agents
        ],
        grants=[_grant_out(grant, agent) for grant, agent in grants],
    )


@router.put(
    "/{user_id}/agent-grants/{agent_id}",
    response_model=AdminAgentGrantOut,
)
async def set_panel_user_agent_grant(
    user_id: str,
    agent_id: str,
    data: AdminAgentGrantUpdate,
    current: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _user_or_404(db, user_id)
    agent = await _agent_or_404(db, agent_id)
    try:
        grant = await admin_agent_access_service.set_grant(
            db,
            admin_user_id=user.id,
            role_key=user.role,
            agent_id=agent.id,
            permissions=data.permissions,
            created_by=str(current.id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.refresh(grant)
    return _grant_out(grant, agent)


@router.delete(
    "/{user_id}/agent-grants/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_panel_user_agent_grant(
    user_id: str,
    agent_id: str,
    current: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _user_or_404(db, user_id)
    agent = await _agent_or_404(db, agent_id)
    await admin_agent_access_service.revoke_grant(
        db,
        admin_user_id=user.id,
        agent_id=agent.id,
        updated_by=str(current.id),
    )
    return None


@router.post("/", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_panel_user(data: PanelUserCreate, db: AsyncSession = Depends(get_db)):
    email = data.email.lower()
    if (await db.execute(select(AdminUser.id).where(AdminUser.email == email))).first():
        raise HTTPException(
            status_code=409, detail="Ya existe un usuario con ese email"
        )
    await _role_or_422(db, data.role)
    user = AdminUser(
        email=email,
        name=data.name.strip(),
        hashed_password=hash_password(data.password),
        role=data.role,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return await _out(db, user)


@router.patch("/{user_id}", response_model=AdminUserOut)
async def update_panel_user(
    user_id: str,
    data: PanelUserUpdate,
    current: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _user_or_404(db, user_id)
    payload = data.model_dump(exclude_unset=True)
    if payload.get("role") is not None:
        await _role_or_422(db, payload["role"])
    if user.id == current.id and payload.get("is_active") is False:
        raise HTTPException(
            status_code=409, detail="No puede desactivar su propia cuenta"
        )
    removes_global_access = await _role_has_global_access(db, user.role) and (
        payload.get("is_active") is False
        or (
            payload.get("role") is not None
            and not await _role_has_global_access(db, payload["role"])
        )
    )
    if removes_global_access:
        global_admins = (
            await db.execute(
                select(func.count())
                .select_from(AdminUser)
                .join(AdminRole, AdminRole.key == AdminUser.role)
                .where(
                    AdminUser.is_active == True,  # noqa: E712
                    AdminRole.is_active == True,  # noqa: E712
                    AdminRole.permissions.contains(["*"]),
                )
            )
        ).scalar_one()
        if global_admins <= 1:
            raise HTTPException(
                status_code=409, detail="Debe quedar al menos un administrador activo"
            )
    for key, value in payload.items():
        setattr(user, key, value.strip() if key == "name" else value)
    await db.flush()
    return await _out(db, user)


@router.post("/{user_id}/reset-password")
async def reset_panel_user_password(
    user_id: str,
    data: PanelUserPasswordReset,
    db: AsyncSession = Depends(get_db),
):
    user = await _user_or_404(db, user_id)
    user.hashed_password = hash_password(data.password)
    user.must_change_password = False
    return {"detail": "Contraseña actualizada"}
