"""Administration API contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


# ---------------------------------------------------------------------------
# AdminUser
# ---------------------------------------------------------------------------


class AdminUserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    must_change_password: bool
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(
        cls, obj, permissions: list[str] | None = None
    ) -> "AdminUserOut":
        return cls(
            id=str(obj.id),
            email=obj.email,
            name=obj.name,
            role=obj.role,
            is_active=obj.is_active,
            must_change_password=obj.must_change_password,
            permissions=sorted(permissions or []),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class AdminRoleOut(BaseModel):
    key: str
    name: str
    description: str | None
    permissions: list[str]
    is_active: bool
    is_system: bool


class PanelUserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(min_length=1, max_length=40)


class PanelUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = Field(default=None, min_length=1, max_length=40)
    is_active: bool | None = None


class PanelUserPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=200)


# ---------------------------------------------------------------------------
# AgentProfile
# ---------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100)
    is_public: bool = False
    retention_days: int = Field(default=30, ge=1, le=365)
    description: str | None = None
    prompt_identity: str = Field(min_length=1)
    prompt_domain: str = Field(min_length=1)
    prompt_guardrails: str = Field(min_length=1)
    unauthorized_message: str = ""
    error_message: str = ""


class ProfileUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    is_public: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)
    description: str | None = None
    prompt_identity: str | None = None
    prompt_domain: str | None = None
    prompt_guardrails: str | None = None
    unauthorized_message: str | None = None
    error_message: str | None = None


class ProfileOut(BaseModel):
    id: str
    name: str
    slug: str
    version: int
    is_active: bool
    is_public: bool
    retention_days: int
    description: str | None
    prompt_identity: str
    prompt_domain: str
    prompt_guardrails: str
    unauthorized_message: str
    error_message: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> "ProfileOut":
        return cls(
            id=str(obj.id),
            name=obj.name,
            slug=obj.slug,
            version=obj.version,
            is_active=obj.is_active,
            is_public=obj.is_public,
            retention_days=obj.retention_days,
            description=obj.description,
            prompt_identity=obj.prompt_identity,
            prompt_domain=obj.prompt_domain,
            prompt_guardrails=obj.prompt_guardrails,
            unauthorized_message=obj.unauthorized_message,
            error_message=obj.error_message,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            created_by=obj.created_by,
        )


# ---------------------------------------------------------------------------
# KnowledgeBlock
# ---------------------------------------------------------------------------


class KnowledgeBlockCreate(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1)
    is_enabled: bool = True
    sort_order: int = 100


class KnowledgeBlockUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    is_enabled: bool | None = None
    sort_order: int | None = None


class KnowledgeBlockOut(BaseModel):
    id: str
    key: str
    title: str
    content: str
    is_enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> "KnowledgeBlockOut":
        return cls(
            id=str(obj.id),
            key=obj.key,
            title=obj.title,
            content=obj.content,
            is_enabled=obj.is_enabled,
            sort_order=obj.sort_order,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


# ---------------------------------------------------------------------------
# ToolConfig
# ---------------------------------------------------------------------------


class HttpConfig(BaseModel):
    """Declarative HTTP operation bound to a trusted integration source."""

    method: str = "GET"
    path: str
    param_location: str = "query"
    parameter_locations: dict[str, str] = Field(default_factory=dict)
    header_names: dict[str, str] = Field(default_factory=dict)
    require_any: list[str] | None = None
    idempotency_key_param: str | None = None

    @field_validator("method")
    @classmethod
    def _allowed_method(cls, v: str) -> str:
        v = (v or "GET").upper()
        if v not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Método HTTP no soportado.")
        return v

    @field_validator("path")
    @classmethod
    def _path_relative(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.startswith("/"):
            raise ValueError("El path debe ser relativo a la fuente y empezar con '/'.")
        if "://" in v:
            raise ValueError("El path no puede ser una URL absoluta.")
        return v

    @field_validator("parameter_locations")
    @classmethod
    def _parameter_locations(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"path", "query", "body", "header"}
        normalized = {
            str(key): str(location).lower() for key, location in value.items()
        }
        invalid = sorted(set(normalized.values()) - allowed)
        if invalid:
            raise ValueError(
                "Ubicaciones de parámetros inválidas: " + ", ".join(invalid)
            )
        return normalized

    @field_validator("param_location")
    @classmethod
    def _param_location(cls, v: str) -> str:
        v = (v or "query").lower()
        if v not in ("query", "body"):
            raise ValueError("param_location debe ser 'query' o 'body'.")
        return v

    @field_validator("require_any")
    @classmethod
    def _require_any(cls, v: list[str] | None) -> list[str] | None:
        if not v:
            return None
        out = []
        for item in v:
            name = (item or "").strip()
            if name and name not in out:
                out.append(name)
        return out or None


def _validate_result_type(v: str) -> str:
    v = (v or "json").lower()
    if v not in ("json", "file"):
        raise ValueError("result_type debe ser 'json' o 'file'.")
    return v


class ToolConfigCreate(BaseModel):
    """Alta de una tool tipo API (handler_kind='http_api') desde el panel."""

    tool_name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    params_schema: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    cost_category: str = "low"
    result_type: str = "json"
    is_enabled: bool = True
    source_id: str
    allowed_channels: list[str] = Field(default_factory=lambda: ["whatsapp"])
    risk_level: str = "read_only"
    requires_confirmation: bool = False
    http_config: HttpConfig

    @field_validator("tool_name")
    @classmethod
    def _name_slug(cls, v: str) -> str:
        import re

        v = (v or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(
                "tool_name debe ser snake_case: minúsculas, números y '_', empezando con letra."
            )
        return v

    @field_validator("result_type")
    @classmethod
    def _rt(cls, v: str) -> str:
        return _validate_result_type(v)

    @field_validator("allowed_channels")
    @classmethod
    def _channels(cls, value: list[str]) -> list[str]:
        allowed = {"web", "whatsapp", "api"}
        normalized = sorted({str(item).lower() for item in value})
        if not normalized or set(normalized) - allowed:
            raise ValueError("allowed_channels contiene valores inválidos")
        return normalized

    @field_validator("risk_level")
    @classmethod
    def _risk(cls, value: str) -> str:
        value = value.lower()
        if value not in {"read_only", "idempotent", "write"}:
            raise ValueError("risk_level inválido")
        return value

    @model_validator(mode="after")
    def _side_effect_policy(self) -> "ToolConfigCreate":
        if self.risk_level == "write":
            if not self.requires_confirmation:
                raise ValueError("write operations require explicit confirmation")
            if not self.http_config.idempotency_key_param:
                raise ValueError(
                    "write operations require an idempotency key parameter"
                )
        return self


class ToolConfigUpdate(BaseModel):
    description: str | None = None
    is_enabled: bool | None = None
    params_schema: dict | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    cost_category: str | None = None
    result_type: str | None = None
    # Solo aplica a tools http_api; el router lo ignora para native/database.
    http_config: HttpConfig | None = None
    source_id: str | None = None
    allowed_channels: list[str] | None = None
    risk_level: str | None = None
    requires_confirmation: bool | None = None

    @field_validator("result_type")
    @classmethod
    def _rt(cls, value: str | None) -> str | None:
        return _validate_result_type(value) if value is not None else None

    @field_validator("allowed_channels")
    @classmethod
    def _channels(cls, value: list[str] | None) -> list[str] | None:
        return ToolConfigCreate._channels(value) if value is not None else None

    @field_validator("risk_level")
    @classmethod
    def _risk(cls, value: str | None) -> str | None:
        return ToolConfigCreate._risk(value) if value is not None else None


class ToolConfigOut(BaseModel):
    id: str
    tool_name: str
    description: str | None
    source_system: str
    source_id: str | None
    is_enabled: bool
    params_schema: dict
    timeout_seconds: int
    cost_category: str
    result_type: str
    handler_kind: str
    http_config: dict | None
    allowed_channels: list[str]
    risk_level: str
    requires_confirmation: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> "ToolConfigOut":
        return cls(
            id=str(obj.id),
            tool_name=obj.tool_name,
            description=obj.description,
            source_system=obj.source_system,
            source_id=str(obj.source_id) if obj.source_id else None,
            is_enabled=obj.is_enabled,
            params_schema=obj.params_schema or {},
            timeout_seconds=obj.timeout_seconds,
            cost_category=obj.cost_category,
            result_type=obj.result_type,
            handler_kind=getattr(obj, "handler_kind", "native"),
            http_config=getattr(obj, "http_config", None),
            allowed_channels=list(getattr(obj, "allowed_channels", None) or []),
            risk_level=getattr(obj, "risk_level", "read_only"),
            requires_confirmation=bool(getattr(obj, "requires_confirmation", False)),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class ConversationSummaryOut(BaseModel):
    id: str
    agent_slug: str
    principal_id: str
    display_name: str | None
    channel: str
    route_key: str
    external_thread_id: str
    status: str
    message_count: int
    last_message_at: datetime | None
    transcript_consent: bool
    consent_version: str | None


class ConversationMessageOut(BaseModel):
    id: str
    role: str
    content: str
    status: str
    tool_names: list[str]
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, obj) -> "ConversationMessageOut":
        return cls(
            id=str(obj.id),
            role=obj.role,
            content=obj.content,
            status=obj.status,
            tool_names=list(obj.tool_names or []),
            metadata=dict(obj.metadata_json or {}),
            created_at=obj.created_at,
        )


class SummaryUpdateRequest(BaseModel):
    conversation_summary: str | None = None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditLogAdminOut(BaseModel):
    id: str
    request_id: str
    phone_number: str
    user_name: str | None = None
    channel: str
    input_type: str
    intent: str | None
    source_system: str | None
    tool_used: str | None
    duration_ms: int | None
    status: str
    error_code: str | None
    error_message: str | None
    response_preview: str | None
    user_message: str | None = None
    tool_calls: list[dict[str, Any]] = []
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj, user_name: str | None = None) -> "AuditLogAdminOut":
        return cls(
            id=str(obj.id),
            request_id=str(obj.request_id),
            phone_number=obj.phone_number,
            user_name=user_name,
            channel=obj.channel,
            input_type=obj.input_type,
            intent=obj.intent,
            source_system=obj.source_system,
            tool_used=obj.tool_used,
            duration_ms=obj.duration_ms,
            status=obj.status,
            error_code=obj.error_code,
            error_message=obj.error_message,
            response_preview=obj.response_preview,
            user_message=getattr(obj, "user_message", None),
            tool_calls=getattr(obj, "tool_calls", None) or [],
            created_at=obj.created_at,
        )


# ---------------------------------------------------------------------------
# Metrics / Dashboard
# ---------------------------------------------------------------------------


class ToolUsageStat(BaseModel):
    tool_name: str
    count: int


class MetricsDashboard(BaseModel):
    messages_today: int
    messages_7d: int
    messages_30d: int
    active_users_7d: int
    errors_24h: int
    top_tools: list[ToolUsageStat]
    delivery_stats: dict[
        str, int
    ]  # {accepted: N, sent: N, delivered: N, read: N, failed: N}
