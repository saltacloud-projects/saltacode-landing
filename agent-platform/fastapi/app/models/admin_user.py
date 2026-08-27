"""
Agent Platform — Modelo: AdminUser
Administradores del panel web. Separado de AuthorizedUser (usuarios WhatsApp).
"""

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class AdminUser(TimestampedModel):
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("admin_roles.key", onupdate="CASCADE", ondelete="RESTRICT"),
        default="admin",
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
