"""
Router: Governance
/internal/governance/* — control de acceso y whitelist
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.dependencies import get_db
from app.schemas.governance import (
    AccessCheckRequest,
    AccessCheckResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.governance import governance_service

router = APIRouter(tags=["governance"], dependencies=[Depends(require_api_key)])


@router.post("/check-access", response_model=AccessCheckResponse)
async def check_access(req: AccessCheckRequest, db: AsyncSession = Depends(get_db)):
    """Verifica autorización + cuota de un número."""
    return await governance_service.check_access(db, req)


@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    users = await governance_service.list_users(db)
    return [UserOut.from_orm_model(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await governance_service.get_user(db, data.phone_number)
    if existing:
        raise HTTPException(status_code=409, detail="El número ya está registrado")
    user = await governance_service.create_user(db, data)
    await db.commit()
    await db.refresh(user)
    return UserOut.from_orm_model(user)


@router.get("/users/{phone}", response_model=UserOut)
async def get_user(phone: str, db: AsyncSession = Depends(get_db)):
    user = await governance_service.get_user(db, phone)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return UserOut.from_orm_model(user)


@router.patch("/users/{phone}", response_model=UserOut)
async def update_user(phone: str, data: UserUpdate, db: AsyncSession = Depends(get_db)):
    user = await governance_service.update_user(db, phone, data)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    await db.commit()
    await db.refresh(user)
    return UserOut.from_orm_model(user)
