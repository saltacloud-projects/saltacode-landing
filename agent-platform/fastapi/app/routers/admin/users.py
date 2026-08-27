"""
Agent Platform — Router: Admin Users
/api/admin/users/* — CRUD de usuarios WhatsApp (authorized_users).
Reutiliza governance_service para la lógica de negocio.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.routers.admin.auth import require_admin_role, require_permission
from app.schemas.governance import UserCreate, UserOut, UserUpdate
from app.services.admin_rbac import AdminPermission
from app.services.governance import governance_service

router = APIRouter(
    tags=["admin-users"],
    dependencies=[Depends(require_permission(AdminPermission.USERS_READ))],
)


@router.get("/", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    users = await governance_service.list_users(db)
    area_map = await governance_service.list_user_area_ids(db)
    return [UserOut.from_orm_model(u, area_map.get(u.id, [])) for u in users]


@router.get("/{phone}", response_model=UserOut)
async def get_user(phone: str, db: AsyncSession = Depends(get_db)):
    user = await governance_service.get_user(db, phone)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    area_ids = await governance_service.get_user_area_id_strings(db, user.id)
    return UserOut.from_orm_model(user, area_ids)


@router.post(
    "/",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_role)],
)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await governance_service.get_user(db, data.phone_number)
    if existing:
        raise HTTPException(status_code=409, detail="El número ya está registrado")
    try:
        user = await governance_service.create_user(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.flush()
    await db.refresh(user)
    area_ids = await governance_service.get_user_area_id_strings(db, user.id)
    return UserOut.from_orm_model(user, area_ids)


@router.patch(
    "/{phone}",
    response_model=UserOut,
    dependencies=[Depends(require_admin_role)],
)
async def update_user(phone: str, data: UserUpdate, db: AsyncSession = Depends(get_db)):
    try:
        user = await governance_service.update_user(db, phone, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    await db.flush()
    await db.refresh(user)
    area_ids = await governance_service.get_user_area_id_strings(db, user.id)
    return UserOut.from_orm_model(user, area_ids)
