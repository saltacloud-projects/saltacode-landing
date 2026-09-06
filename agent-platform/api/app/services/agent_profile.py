"""
AgentProfileService
Carga el perfil activo del agente desde DB con cache Redis.
Si no hay perfil activo, retorna None (el ConfigurationService bloquea el pipeline).
"""

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_profile import AgentProfile

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutos


class AgentProfileService:
    async def get_profile(
        self,
        db: AsyncSession,
        *,
        profile_id: uuid.UUID | str | None = None,
        slug: str | None = None,
        active_only: bool = True,
        redis=None,
    ) -> AgentProfile | None:
        """Resolve one profile explicitly by id or slug with per-agent caching."""
        if (profile_id is None) == (slug is None):
            raise ValueError("exactly one of profile_id or slug is required")

        parsed_id: uuid.UUID | None = None
        if profile_id is not None:
            try:
                parsed_id = (
                    profile_id
                    if isinstance(profile_id, uuid.UUID)
                    else uuid.UUID(profile_id)
                )
            except ValueError:
                return None
            cache_key = f"agent_profile:id:{parsed_id}"
        else:
            normalized_slug = str(slug).strip()
            if not normalized_slug:
                return None
            cache_key = f"agent_profile:slug:{normalized_slug}"

        if redis:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    profile = self._deserialize(cached)
                    if not active_only or profile.is_active:
                        return profile
            except Exception as exc:
                logger.warning("agent_profile_cache_miss", extra={"error": str(exc)})

        stmt = select(AgentProfile)
        if parsed_id is not None:
            stmt = stmt.where(AgentProfile.id == parsed_id)
        else:
            stmt = stmt.where(AgentProfile.slug == normalized_slug)
        if active_only:
            stmt = stmt.where(AgentProfile.is_active == True)  # noqa: E712
        profile = (await db.execute(stmt.limit(1))).scalar_one_or_none()
        if profile is None:
            return None

        if redis:
            try:
                payload = json.dumps(self._serialize(profile))
                await redis.setex(f"agent_profile:id:{profile.id}", _CACHE_TTL, payload)
                await redis.setex(
                    f"agent_profile:slug:{profile.slug}", _CACHE_TTL, payload
                )
            except Exception as exc:
                logger.warning(
                    "agent_profile_cache_write_error", extra={"error": str(exc)}
                )
        return profile

    async def get_active_profile(
        self, db: AsyncSession, redis=None
    ) -> AgentProfile | None:
        """
        Retorna el perfil activo del agente.
        Prioridad: Redis cache → PostgreSQL → None (sin perfil activo).
        """
        profile = await self.get_profile(
            db,
            slug=settings.default_agent_slug,
            active_only=True,
            redis=redis,
        )
        if profile is None:
            logger.warning("agent_profile_not_found")
        return profile

    @staticmethod
    def _serialize(profile: AgentProfile) -> dict:
        return {
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

    @staticmethod
    def _deserialize(payload: str) -> AgentProfile:
        data = json.loads(payload)
        data["id"] = uuid.UUID(data["id"])
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return AgentProfile(**data)


agent_profile_service = AgentProfileService()
