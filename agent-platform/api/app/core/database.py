"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Engine async con configuración de pool para producción en un nodo
engine = create_async_engine(
    settings.postgres_dsn,
    echo=False,  # True solo para debug de queries
    pool_pre_ping=True,  # verifica conexiones antes de usarlas
    pool_size=5,  # conexiones persistentes en el pool
    max_overflow=10,  # conexiones adicionales permitidas bajo carga
    pool_recycle=1800,  # recicla conexiones cada 30 min
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos ORM del microservicio."""

    pass
