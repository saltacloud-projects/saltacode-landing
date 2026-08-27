"""Admin contracts for integration sources and write-only credentials."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

_AUTH_TYPES = {"none", "bearer", "token", "api_key", "basic"}


class IntegrationSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=100)
    source_type: str = "http"
    base_url: str = Field(min_length=1, max_length=2048)
    allowed_hosts: list[str] = Field(default_factory=list)
    auth_type: str = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, str] | None = Field(default=None, repr=False)
    default_headers: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True
    is_public: bool = False
    verify_tls: bool = True
    allow_private_network: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_response_bytes: int = Field(default=2_000_000, ge=1_024, le=20_000_000)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", value):
            raise ValueError("slug must use lowercase letters, numbers and hyphens")
        return value

    @field_validator("source_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.lower()
        if value != "http":
            raise ValueError("only http sources are supported in this release")
        return value

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: str) -> str:
        value = value.lower()
        if value not in _AUTH_TYPES:
            raise ValueError(
                f"auth_type must be one of: {', '.join(sorted(_AUTH_TYPES))}"
            )
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_hosts(cls, value: list[str]) -> list[str]:
        return sorted(
            {item.strip().lower().rstrip(".") for item in value if item.strip()}
        )

    @field_validator("default_headers")
    @classmethod
    def reject_secret_headers(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = {"authorization", "proxy-authorization", "cookie", "set-cookie"}
        if forbidden.intersection(key.lower() for key in value):
            raise ValueError(
                "secret-bearing headers must be configured through credentials"
            )
        return value

    @model_validator(mode="after")
    def validate_url(self) -> "IntegrationSourceCreate":
        parsed = urlsplit(self.base_url.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "base_url cannot contain credentials, query parameters or fragments"
            )
        if parsed.scheme != "https" and not self.allow_private_network:
            raise ValueError("public sources must use HTTPS")
        hostname = parsed.hostname.lower().rstrip(".")
        if not self.allowed_hosts:
            self.allowed_hosts = [hostname]
        if hostname not in self.allowed_hosts:
            raise ValueError("base_url hostname must be present in allowed_hosts")
        self.base_url = self.base_url.strip().rstrip("/")
        return self


class IntegrationSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    allowed_hosts: list[str] | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = Field(default=None, repr=False)
    clear_credentials: bool = False
    default_headers: dict[str, str] | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    verify_tls: bool | None = None
    allow_private_network: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    max_response_bytes: int | None = Field(default=None, ge=1_024, le=20_000_000)

    @model_validator(mode="after")
    def validate_credential_action(self) -> "IntegrationSourceUpdate":
        if self.clear_credentials and self.credentials is not None:
            raise ValueError("credentials and clear_credentials are mutually exclusive")
        return self


class IntegrationSourceOut(BaseModel):
    id: str
    name: str
    slug: str
    source_type: str
    base_url: str
    allowed_hosts: list[str]
    auth_type: str
    auth_config: dict[str, Any]
    default_headers: dict[str, str]
    has_credentials: bool
    is_active: bool
    is_public: bool
    verify_tls: bool
    allow_private_network: bool
    timeout_seconds: int
    max_response_bytes: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, source) -> "IntegrationSourceOut":
        return cls(
            id=str(source.id),
            name=source.name,
            slug=source.slug,
            source_type=source.source_type,
            base_url=source.base_url,
            allowed_hosts=list(source.allowed_hosts or []),
            auth_type=source.auth_type,
            auth_config=dict(source.auth_config or {}),
            default_headers=dict(source.default_headers or {}),
            has_credentials=bool(source.encrypted_credentials),
            is_active=source.is_active,
            is_public=source.is_public,
            verify_tls=source.verify_tls,
            allow_private_network=source.allow_private_network,
            timeout_seconds=source.timeout_seconds,
            max_response_bytes=source.max_response_bytes,
            created_by=source.created_by,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


class IntegrationSourceTestRequest(BaseModel):
    path: str = "/"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/") or "://" in value:
            raise ValueError("path must be relative and start with '/'")
        return value


class IntegrationSourceTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    duration_ms: int
    content_type: str | None = None
    error_code: str | None = None
