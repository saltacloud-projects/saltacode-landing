"""Admin CRUD for independently addressable agent profiles."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.agent_profile import AgentProfile
from app.routers.admin.auth import require_admin_role, require_permission
from app.schemas.admin import ProfileCreate, ProfileOut, ProfileUpdate
from app.services.admin_rbac import AdminPermission

router = APIRouter(
    tags=["admin-profiles"],
    dependencies=[Depends(require_permission(AdminPermission.PROFILES_READ))],
)


@router.get("/", response_model=list[ProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentProfile).order_by(
            AgentProfile.is_active.desc(), AgentProfile.updated_at.desc()
        )
    )
    return [ProfileOut.from_orm_model(p) for p in result.scalars().all()]


@router.get("/{profile_id}", response_model=ProfileOut)
async def get_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    profile = await _get_or_404(db, profile_id)
    return ProfileOut.from_orm_model(profile)


@router.post(
    "/",
    response_model=ProfileOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_role)],
)
async def create_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    profile = AgentProfile(
        name=data.name,
        slug=data.slug,
        is_public=data.is_public,
        retention_days=data.retention_days,
        description=data.description,
        prompt_identity=data.prompt_identity,
        prompt_domain=data.prompt_domain,
        prompt_guardrails=data.prompt_guardrails,
        unauthorized_message=data.unauthorized_message,
        error_message=data.error_message,
        is_active=False,
        created_by="admin_panel",
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return ProfileOut.from_orm_model(profile)


@router.patch(
    "/{profile_id}",
    response_model=ProfileOut,
    dependencies=[Depends(require_admin_role)],
)
async def update_profile(
    profile_id: str, data: ProfileUpdate, db: AsyncSession = Depends(get_db)
):
    profile = await _get_or_404(db, profile_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(profile, field, value)
    await db.flush()
    await db.refresh(profile)
    return ProfileOut.from_orm_model(profile)


@router.post(
    "/{profile_id}/activate",
    response_model=ProfileOut,
    dependencies=[Depends(require_admin_role)],
)
async def activate_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """Activate one addressable profile without disabling other agents."""
    profile = await _get_or_404(db, profile_id)
    profile.is_active = True
    await db.flush()
    await db.refresh(profile)
    return ProfileOut.from_orm_model(profile)


async def _get_or_404(db: AsyncSession, profile_id: str) -> AgentProfile:
    try:
        uid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    result = await db.execute(select(AgentProfile).where(AgentProfile.id == uid))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return profile
