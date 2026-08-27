"""Write-only admin contracts for agent runtime and reusable connections."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RouteKey = str


def _reject_secret_settings(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    forbidden = {
        "api_key",
        "access_token",
        "verify_token",
        "app_secret",
        "authorization",
        "password",
        "secret",
        "cookie",
    }

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = str(key).strip().lower()
                if normalized in forbidden or normalized.endswith(
                    ("_password", "_secret")
                ):
                    raise ValueError(
                        "secret values must be stored in credentials, not settings"
                    )
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return value


class OpenAICredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, repr=False)


class WhatsAppCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=1, repr=False)
    verify_token: str = Field(min_length=1, repr=False)
    app_secret: str = Field(min_length=1, repr=False)


class ProviderConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=100)
    provider_type: Literal["openai"] = "openai"
    base_url: str | None = Field(default=None, max_length=2048)
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials: OpenAICredentials | None = Field(default=None, repr=False)
    is_active: bool = True

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", value):
            raise ValueError("slug must use lowercase letters, numbers and hyphens")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "base_url cannot contain credentials, query parameters or fragments"
            )
        return value.strip().rstrip("/")

    _settings = field_validator("settings")(_reject_secret_settings)


class ProviderConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str | None = Field(default=None, max_length=2048)
    settings: dict[str, Any] | None = None
    credentials: OpenAICredentials | None = Field(default=None, repr=False)
    clear_credentials: bool = False
    is_active: bool | None = None

    _base_url = field_validator("base_url")(
        ProviderConnectionCreate.validate_base_url.__func__
    )
    _settings = field_validator("settings")(_reject_secret_settings)

    @model_validator(mode="after")
    def exclusive_credential_action(self):
        if self.clear_credentials and self.credentials is not None:
            raise ValueError("credentials and clear_credentials are mutually exclusive")
        return self


class ProviderConnectionOut(BaseModel):
    id: str
    name: str
    slug: str
    provider_type: str
    base_url: str | None
    settings: dict[str, Any]
    has_credentials: bool
    is_active: bool
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row):
        return cls(
            id=str(row.id),
            name=row.name,
            slug=row.slug,
            provider_type=row.provider_type,
            base_url=row.base_url,
            settings=dict(row.settings_json or {}),
            has_credentials=bool(row.encrypted_credentials),
            is_active=row.is_active,
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ChannelConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=100)
    channel: Literal["web", "whatsapp"]
    external_account_id: str | None = Field(default=None, max_length=255)
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials: WhatsAppCredentials | None = Field(default=None, repr=False)
    is_active: bool = True

    _slug = field_validator("slug")(ProviderConnectionCreate.normalize_slug.__func__)
    _settings = field_validator("settings")(_reject_secret_settings)

    @model_validator(mode="after")
    def reject_web_credentials(self):
        if self.channel == "web" and self.credentials is not None:
            raise ValueError("web connections do not accept credentials")
        return self


class ChannelConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    external_account_id: str | None = Field(default=None, max_length=255)
    settings: dict[str, Any] | None = None
    credentials: WhatsAppCredentials | None = Field(default=None, repr=False)
    clear_credentials: bool = False
    is_active: bool | None = None
    _settings = field_validator("settings")(_reject_secret_settings)

    @model_validator(mode="after")
    def exclusive_credential_action(self):
        if self.clear_credentials and self.credentials is not None:
            raise ValueError("credentials and clear_credentials are mutually exclusive")
        return self


class ChannelConnectionOut(BaseModel):
    id: str
    name: str
    slug: str
    channel: str
    external_account_id: str | None
    settings: dict[str, Any]
    has_credentials: bool
    is_active: bool
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row):
        return cls(
            id=str(row.id),
            name=row.name,
            slug=row.slug,
            channel=row.channel,
            external_account_id=row.external_account_id,
            settings=dict(row.settings_json or {}),
            has_credentials=bool(row.encrypted_credentials),
            is_active=row.is_active,
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ConnectionTestResult(BaseModel):
    ok: bool
    duration_ms: int
    error_code: str | None = None


class AgentRuntimeUpdate(BaseModel):
    provider_connection_id: str | None = None
    chat_model: str | None = Field(default=None, min_length=1, max_length=160)
    transcription_model: str | None = Field(default=None, min_length=1, max_length=160)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=128_000)
    max_iterations: int | None = Field(default=None, ge=1, le=50)
    max_tool_calls: int | None = Field(default=None, ge=0, le=200)
    loop_timeout_seconds: int | None = Field(default=None, ge=1, le=900)
    tool_timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    tool_result_max_chars: int | None = Field(default=None, ge=256, le=100_000)
    history_message_limit: int | None = Field(default=None, ge=0, le=200)
    history_cache_ttl_seconds: int | None = Field(default=None, ge=0, le=86_400)
    summary_enabled: bool | None = None
    summary_trigger_messages: int | None = Field(default=None, ge=1, le=1_000)
    summary_max_chars: int | None = Field(default=None, ge=1_000, le=500_000)
    rag_enabled: bool | None = None
    rag_retrieval_top_k: int | None = Field(default=None, ge=1, le=50)
    rag_min_relevance_score: float | None = Field(default=None, ge=0, le=1)
    rag_vector_weight: float | None = Field(default=None, ge=0, le=1)
    rag_lexical_weight: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_rag_weights(self):
        if self.rag_vector_weight is not None and self.rag_lexical_weight is not None:
            total = self.rag_vector_weight + self.rag_lexical_weight
            if abs(total - 1.0) > 1e-6:
                raise ValueError("RAG vector and lexical weights must sum to 1")
        return self


class AgentRuntimeOut(AgentRuntimeUpdate):
    id: str
    agent_id: str
    provider_connection_id: str | None
    chat_model: str
    transcription_model: str
    temperature: float
    max_output_tokens: int
    max_iterations: int
    max_tool_calls: int
    loop_timeout_seconds: int
    tool_timeout_seconds: int
    tool_result_max_chars: int
    history_message_limit: int
    history_cache_ttl_seconds: int
    summary_enabled: bool
    summary_trigger_messages: int
    summary_max_chars: int
    rag_enabled: bool
    rag_retrieval_top_k: int
    rag_min_relevance_score: float
    rag_vector_weight: float
    rag_lexical_weight: float
    provider_ready: bool = False

    @classmethod
    def from_model(cls, row, *, provider_ready: bool):
        data = {
            field: getattr(row, field)
            for field in cls.model_fields
            if hasattr(row, field)
        }
        data.update(
            id=str(row.id),
            agent_id=str(row.agent_id),
            provider_connection_id=str(row.provider_connection_id)
            if row.provider_connection_id
            else None,
            provider_ready=provider_ready,
        )
        return cls(**data)


class AgentRouteCreate(BaseModel):
    channel: Literal["web", "whatsapp"]
    route_key: str = Field(
        min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._:-]{0,119}$"
    )
    channel_connection_id: str
    is_active: bool = True


class AgentRouteUpdate(BaseModel):
    channel_connection_id: str | None = None
    is_active: bool | None = None


class AgentRouteOut(BaseModel):
    id: str
    agent_id: str
    channel: str
    route_key: str
    channel_connection_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row):
        return cls(
            id=str(row.id),
            agent_id=str(row.agent_id),
            channel=row.channel,
            route_key=row.route_key,
            channel_connection_id=str(row.channel_connection_id),
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
