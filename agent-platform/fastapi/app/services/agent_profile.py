"""
AgentProfileService
Carga el perfil activo del agente desde DB con cache Redis.
Si no hay perfil activo, retorna None (el ConfigurationService bloquea el pipeline).
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_profile import AgentProfile

logger = logging.getLogger(__name__)

_CACHE_KEY = "agent_profile:active"
_CACHE_TTL = 300  # 5 minutos


class AgentProfileService:
    async def get_active_profile(
        self, db: AsyncSession, redis=None
    ) -> AgentProfile | None:
        """
        Retorna el perfil activo del agente.
        Prioridad: Redis cache → PostgreSQL → None (sin perfil activo).
        """
        # 1. Intentar desde cache
        if redis:
            try:
                cached = await redis.get(_CACHE_KEY)
                if cached:
                    data = json.loads(cached)
                    profile = AgentProfile(**data)
                    return profile
            except Exception as e:
                logger.warning("agent_profile_cache_miss", extra={"error": str(e)})

        # 2. Desde PostgreSQL
        result = await db.execute(
            select(AgentProfile)
            .where(
                AgentProfile.slug == settings.default_agent_slug,
                AgentProfile.is_active == True,  # noqa: E712
            )
            .limit(1)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            logger.warning("agent_profile_not_found")
            return None

        # 3. Guardar en cache
        if redis:
            try:
                data = {
                    "id": str(profile.id),
                    "name": profile.name,
                    "slug": profile.slug,
                    "version": profile.version,
                    "is_active": profile.is_active,
                    "is_public": profile.is_public,
                    "retention_days": profile.retention_days,
                    "description": profile.description,
                    "prompt_identity": profile.prompt_identity,
                    "prompt_domain": profile.prompt_domain,
                    "prompt_guardrails": profile.prompt_guardrails,
                    "unauthorized_message": profile.unauthorized_message,
                    "error_message": profile.error_message,
                    "created_at": profile.created_at.isoformat(),
                    "updated_at": profile.updated_at.isoformat(),
                    "created_by": profile.created_by,
                }
                await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(data))
            except Exception as e:
                logger.warning(
                    "agent_profile_cache_write_error", extra={"error": str(e)}
                )

        return profile


agent_profile_service = AgentProfileService()
