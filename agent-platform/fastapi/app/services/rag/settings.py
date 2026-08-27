"""Acceso centralizado a la configuración RAG persistida."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag import RagSettings


class RagSettingsService:
    async def get(self, db: AsyncSession) -> RagSettings | None:
        result = await db.execute(
            select(RagSettings).where(RagSettings.key == "default")
        )
        return result.scalar_one_or_none()

    async def require(self, db: AsyncSession) -> RagSettings:
        value = await self.get(db)
        if value is None:
            raise RuntimeError("La migración/configuración RAG no está instalada")
        return value


rag_settings_service = RagSettingsService()
