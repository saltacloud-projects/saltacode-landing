"""Shared SQLAlchemy model primitives for the agent platform."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimestampedModel(Base):
    """
    Base abstracta con id UUID y timestamps automáticos.
    Herencia: class MiModelo(TimestampedModel): ...

    Campos incluidos en todas las tablas que hereden de esta clase:
    - id: UUID v4 autogenerado como PK
    - created_at: timestamp de creación (manejado por PostgreSQL)
    - updated_at: timestamp de última modificación (manejado por PostgreSQL)
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
