"""
Agent Platform — Router: Admin Auth
/api/admin/auth/* — autenticación JWT para el panel de administración.
"""

import logging
import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.schemas.admin import (
    AdminUserOut,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.admin_rbac import AdminPermission, admin_rbac_service

router = APIRouter(tags=["admin-auth"])
logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Dependency: require JWT admin
# ---------------------------------------------------------------------------


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """
    Valida el Bearer token JWT y retorna el AdminUser correspondiente.
    Lanza 401 si el token es inválido, expirado o el usuario no existe/inactivo.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    result = await db.execute(select(AdminUser).where(AdminUser.id == uid))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o desactivado",
        )

    return user


async def require_admin_role(
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """Compatibilidad: autoriza sólo roles con permiso global persistido."""
    if not await admin_rbac_service.has_permission(
        db,
        role_key=admin.role,
        permission=AdminPermission.ALL,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol administrador para realizar esta acción",
        )
    return admin


def require_permission(permission: str | AdminPermission) -> Callable:
    """Construye una dependency FastAPI basada en permisos persistidos."""

    async def dependency(
        admin: AdminUser = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
    ) -> AdminUser:
        if not await admin_rbac_service.has_permission(
            db,
            role_key=admin.role,
            permission=permission,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para realizar esta acción",
            )
        return admin

    return dependency


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Autenticar admin con email + password → JWT access + refresh tokens."""
    result = await db.execute(
        select(AdminUser).where(AdminUser.email == data.email.lower())
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario desactivado",
        )

    logger.info("admin_login", extra={"email": user.email})

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.email, user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Renovar access token usando un refresh token válido."""
    payload = decode_token(data.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )

    user_id = payload.get("sub")
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    result = await db.execute(select(AdminUser).where(AdminUser.id == uid))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o desactivado",
        )

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.email, user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=AdminUserOut)
async def me(
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Retorna el usuario admin autenticado."""
    permissions = await admin_rbac_service.permissions_for_role(db, admin.role)
    return AdminUserOut.from_orm_model(admin, list(permissions))


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Cambiar la contraseña del admin autenticado."""
    if not verify_password(data.current_password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contraseña actual incorrecta",
        )

    admin.hashed_password = hash_password(data.new_password)
    admin.must_change_password = False
    logger.info("admin_password_changed", extra={"email": admin.email})
    return {"detail": "Contraseña actualizada"}
