"""
GovernanceService
Control de acceso: whitelist de usuarios autorizados.
Sin permisos por tool ni cuotas.
"""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorized_user import AuthorizedUser
from app.models.rag import AuthorizedUserArea, OrganizationArea
from app.models.tool_config import ToolConfig
from app.schemas.governance import (
    AccessCheckRequest,
    AccessCheckResponse,
    UserCreate,
    UserUpdate,
)

logger = logging.getLogger(__name__)


class GovernanceService:
    async def check_access(
        self, db: AsyncSession, req: AccessCheckRequest
    ) -> AccessCheckResponse:
        user = await self._get_user(db, req.phone_number)

        if user is None:
            return AccessCheckResponse(
                allowed=False,
                reason="Número no autorizado",
            )
        if not user.is_active:
            return AccessCheckResponse(
                allowed=False,
                user={"user_id": str(user.id), "name": user.name},
                reason="Usuario desactivado",
            )

        return AccessCheckResponse(
            allowed=True,
            user={"user_id": str(user.id), "name": user.name},
        )

    async def get_user(
        self, db: AsyncSession, phone_number: str
    ) -> AuthorizedUser | None:
        return await self._get_user(db, phone_number)

    async def list_users(self, db: AsyncSession) -> list[AuthorizedUser]:
        result = await db.execute(
            select(AuthorizedUser).order_by(AuthorizedUser.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_user(self, db: AsyncSession, data: UserCreate) -> AuthorizedUser:
        user = AuthorizedUser(
            phone_number=data.phone_number,
            name=data.name,
            is_active=data.is_active,
            notes=data.notes,
            has_all_area_access=data.has_all_area_access,
        )
        db.add(user)
        await db.flush()
        await self._sync_user_areas(db, user.id, data.area_ids)
        logger.info("user_created", extra={"phone": data.phone_number})
        return user

    async def update_user(
        self, db: AsyncSession, phone: str, data: UserUpdate
    ) -> AuthorizedUser | None:
        user = await self._get_user(db, phone)
        if not user:
            return None
        payload = data.model_dump(exclude_none=True)
        area_ids = payload.pop("area_ids", None)
        for field, value in payload.items():
            setattr(user, field, value)
        if area_ids is not None:
            await self._sync_user_areas(db, user.id, area_ids)
        return user

    async def list_user_area_ids(self, db: AsyncSession) -> dict[uuid.UUID, list[str]]:
        rows = (
            await db.execute(
                select(AuthorizedUserArea.user_id, AuthorizedUserArea.area_id)
            )
        ).all()
        result: dict[uuid.UUID, list[str]] = {}
        for user_id, area_id in rows:
            result.setdefault(user_id, []).append(str(area_id))
        return result

    async def get_user_area_id_strings(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[str]:
        values = (
            (
                await db.execute(
                    select(AuthorizedUserArea.area_id).where(
                        AuthorizedUserArea.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return [str(value) for value in values]

    async def get_available_tools_for_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None,
        runtime_registered_tools: set[str],
    ) -> list[dict]:
        """
        Construye la lista de tools disponibles: habilitadas en DB ∩ registradas
        en runtime. Ya no hay permisos por tool (el agente es uno para todos).
        Si `user_id` es None (fail-closed), retorna [].
        """
        if user_id is None:
            return []

        # 1. Tools habilitadas en DB
        result = await db.execute(
            select(ToolConfig).where(ToolConfig.is_enabled == True)  # noqa: E712
        )
        enabled_tools = [
            {
                "tool_name": t.tool_name,
                "description": t.description or "",
                "source_system": t.source_system,
            }
            for t in result.scalars().all()
        ]

        # 2. Intersectar con runtime (tools efectivamente cargadas)
        if runtime_registered_tools:
            enabled_tools = [
                t for t in enabled_tools if t["tool_name"] in runtime_registered_tools
            ]

        if not enabled_tools:
            return []

        # Ya no hay permisos por tool: el agente es uno para todos los usuarios
        # autorizados. Se devuelven todas las tools habilitadas ∩ runtime.
        return enabled_tools

    # ---------------------------------------------------------------------------
    # Privados
    # ---------------------------------------------------------------------------
    async def _get_user(self, db: AsyncSession, phone: str) -> AuthorizedUser | None:
        result = await db.execute(
            select(AuthorizedUser).where(AuthorizedUser.phone_number == phone)
        )
        return result.scalar_one_or_none()

    async def _sync_user_areas(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        raw_area_ids: list[str],
    ) -> None:
        area_ids: set[uuid.UUID] = set()
        for raw in raw_area_ids:
            try:
                area_ids.add(uuid.UUID(str(raw)))
            except ValueError as exc:
                raise ValueError(f"Área inválida: {raw}") from exc
        # General es siempre acumulativa: asignar un área específica nunca debe
        # quitar documentación común a todos los usuarios autorizados.
        general = (
            await db.execute(
                select(OrganizationArea.id).where(
                    OrganizationArea.is_general == True,  # noqa: E712
                    OrganizationArea.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if general is not None:
            area_ids.add(general)
        if area_ids:
            existing = set(
                (
                    await db.execute(
                        select(OrganizationArea.id).where(
                            OrganizationArea.id.in_(area_ids),
                            OrganizationArea.is_active == True,  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )
            if existing != area_ids:
                raise ValueError("Una o más áreas no existen o están inactivas")
        await db.execute(
            delete(AuthorizedUserArea).where(AuthorizedUserArea.user_id == user_id)
        )
        for area_id in sorted(area_ids, key=str):
            db.add(AuthorizedUserArea(user_id=user_id, area_id=area_id))


governance_service = GovernanceService()
