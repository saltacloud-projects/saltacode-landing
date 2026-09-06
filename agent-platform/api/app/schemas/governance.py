"""
Agent Platform — Schemas de Gobierno
Whitelist de usuarios, cuotas y control de acceso.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# AccessCheck
# ---------------------------------------------------------------------------
class AccessCheckRequest(BaseModel):
    request_id: str
    phone_number: str
    channel: str = "whatsapp"
    agent_id: UUID | None = None


class AccessCheckResponse(BaseModel):
    allowed: bool
    user: dict[str, Any] | None = None  # {"user_id": str, "name": str}
    reason: str | None = None


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    phone_number: str
    name: str | None = None
    is_active: bool = True
    notes: str | None = None
    has_all_area_access: bool = False
    area_ids: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    notes: str | None = None
    has_all_area_access: bool | None = None
    area_ids: list[str] | None = None


class UserOut(BaseModel):
    id: str
    phone_number: str
    name: str | None
    is_active: bool
    notes: str | None
    has_all_area_access: bool
    area_ids: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj, area_ids: list[str] | None = None) -> "UserOut":
        return cls(
            id=str(obj.id),
            phone_number=obj.phone_number,
            name=obj.name,
            is_active=obj.is_active,
            notes=obj.notes,
            has_all_area_access=obj.has_all_area_access,
            area_ids=area_ids or [],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class AgentUserAssignmentUpdate(BaseModel):
    is_active: bool = True
    has_all_area_access: bool = False
    area_ids: list[str] = Field(default_factory=list)


class AgentUserOut(UserOut):
    agent_id: str

    @classmethod
    def from_assignment(
        cls,
        agent_id,
        user,
        binding,
        area_ids: list[str] | None = None,
    ) -> "AgentUserOut":
        return cls(
            agent_id=str(agent_id),
            id=str(user.id),
            phone_number=user.phone_number,
            name=user.name,
            is_active=binding.is_active,
            notes=user.notes,
            has_all_area_access=binding.has_all_area_access,
            area_ids=area_ids or [],
            created_at=binding.created_at,
            updated_at=binding.updated_at,
        )
