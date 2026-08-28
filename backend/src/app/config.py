from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SALTACODE_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Saltacode BFF"
    app_env: Literal["development", "test", "production"] = "development"
    allowed_origins: str = "http://localhost:4321"
    agent_ai_base_url: str | None = None
    agent_route_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9._:-]{0,119}$",
    )
    agent_internal_token: SecretStr | None = Field(default=None, min_length=32)
    agent_internal_token_file: Path | None = None
    session_signing_secret: SecretStr | None = Field(default=None, min_length=32)
    session_signing_secret_file: Path | None = None
    session_cookie_name: str = "saltacode_chat_session"
    session_cookie_max_age_seconds: int = Field(default=2_592_000, ge=300, le=31_536_000)
    chat_privacy_version: str = Field(
        default="saltacode-chat-privacy-2026-08-28",
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    agent_ai_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    agent_ai_response_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_requests: int = Field(default=20, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    redis_url: SecretStr | None = None
    redis_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    redis_response_timeout_seconds: float = Field(default=1.0, gt=0, le=30)

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, value: str) -> str:
        origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("at least one allowed origin is required")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid allowed origin: {origin}")
            if parsed.path or parsed.query or parsed.fragment:
                raise ValueError(f"allowed origin must not contain a path: {origin}")
        return ",".join(origins)

    @field_validator("agent_ai_base_url")
    @classmethod
    def validate_agent_ai_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("agent AI base URL must use http or https")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("agent AI base URL must not contain credentials")
        if parsed.path or parsed.query or parsed.fragment:
            raise ValueError("agent AI base URL must not contain a path")
        return normalized

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
            raise ValueError("Redis URL must use redis or rediss")
        return value

    @model_validator(mode="after")
    def enforce_production_rate_limiter(self) -> "Settings":
        if self.agent_internal_token is not None and self.agent_internal_token_file is not None:
            raise ValueError("configure either agent internal token or token file, not both")
        if self.session_signing_secret is not None and self.session_signing_secret_file is not None:
            raise ValueError("configure either session signing secret or secret file, not both")

        if self.rate_limit_backend == "redis" and self.redis_url is None:
            raise ValueError("Redis rate-limit backend requires a Redis URL")

        if self.app_env != "test" and self.agent_ai_base_url is not None:
            if self.app_env == "production" and self.agent_internal_token_file is None:
                raise ValueError("production requires the agent internal token file")
            if self.resolve_agent_internal_token() is None:
                raise ValueError("agent AI base URL requires an internal token")

        if self.agent_ai_base_url is not None and self.agent_route_key is None:
            raise ValueError("agent AI base URL requires an agent route key")

        if self.app_env == "production":
            missing: list[str] = []
            if self.session_signing_secret_file is None:
                missing.append("a session signing secret file")
            if self.rate_limit_backend != "redis":
                missing.append("a shared rate-limit backend")
            if self.agent_ai_base_url is None:
                missing.append("an agent AI base URL")
            if self.agent_internal_token_file is None:
                missing.append("an agent internal token file")
            if missing:
                raise ValueError(f"production requires {', '.join(missing)}")
        return self

    def resolve_redis_url(self) -> str | None:
        return self.redis_url.get_secret_value() if self.redis_url is not None else None

    def resolve_agent_internal_token(self) -> str | None:
        if self.agent_internal_token is not None:
            return self.agent_internal_token.get_secret_value()
        if self.agent_internal_token_file is None:
            return None
        try:
            token = self.agent_internal_token_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ValueError("agent internal token file is unreadable") from error
        if len(token) < 32:
            raise ValueError("agent internal token file must contain at least 32 characters")
        return token

    def resolve_session_signing_secret(self) -> str | None:
        if self.session_signing_secret is not None:
            return self.session_signing_secret.get_secret_value()
        if self.session_signing_secret_file is None:
            return None
        try:
            secret = self.session_signing_secret_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ValueError("session signing secret file is unreadable") from error
        if len(secret) < 32:
            raise ValueError("session signing secret file must contain at least 32 characters")
        return secret

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        return frozenset(self.allowed_origins.split(","))


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings()
