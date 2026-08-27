"""Roles y permisos persistentes del panel administrativo."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class AdminRole(TimestampedModel):
    __tablename__ = "admin_roles"

    key: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
