"""
Agent Platform — Dependencies compartidas
Inyección de dependencias reutilizables en los routers.
"""

from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency que provee una sesión de base de datos por request.
    Hace commit automático al finalizar, rollback ante excepciones.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_redis(request: Request) -> aioredis.Redis:
    """
    Dependency que provee el cliente Redis compartido (app.state.redis).
    Se inicializa una sola vez en el lifespan de la app.

    Uso en routers:
        @router.get("/endpoint")
        async def endpoint(redis: aioredis.Redis = Depends(get_redis)):
            await redis.set("key", "value")
    """
    return request.app.state.redis
