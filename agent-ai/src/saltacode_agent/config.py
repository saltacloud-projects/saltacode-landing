"""Runtime configuration loaded exclusively from the environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MAX_SECRET_FILE_BYTES = 4_096


class Settings(BaseSettings):
    """Service settings with fail-closed internal authentication."""

    model_config = SettingsConfigDict(
        env_prefix="SALTACODE_AGENT_",
        env_file=None,
        extra="ignore",
    )

    service_name: str = "saltacode-agent"
    environment: Literal["development", "testing", "production"] = "development"
    internal_token: SecretStr | None = Field(default=None, min_length=32)
    internal_token_file: Path | None = None

    @model_validator(mode="after")
    def resolve_internal_token(self) -> "Settings":
        """Resolve one token source without ever retaining plaintext metadata."""

        if self.internal_token is not None and self.internal_token_file is not None:
            raise ValueError("configure exactly one internal token source")

        if self.internal_token_file is not None:
            try:
                with self.internal_token_file.open(encoding="utf-8") as secret_file:
                    raw_token = secret_file.read(_MAX_SECRET_FILE_BYTES + 1)
            except OSError as exc:
                raise ValueError("internal token file is not readable") from exc

            if len(raw_token) > _MAX_SECRET_FILE_BYTES:
                raise ValueError("internal token file is too large")

            token = raw_token.rstrip("\r\n")
            if len(token) < 32 or not token.strip():
                raise ValueError("internal token file must contain at least 32 characters")
            self.internal_token = SecretStr(token)

        if self.internal_token is None:
            raise ValueError("an internal token source is required")

        if self.environment == "production" and self.internal_token_file is None:
            raise ValueError("production requires SALTACODE_AGENT_INTERNAL_TOKEN_FILE")

        return self

    @property
    def resolved_internal_token(self) -> SecretStr:
        """Return the validated token as a redacting secret type."""

        if self.internal_token is None:  # Defensive: the model validator guarantees this.
            raise RuntimeError("internal token was not resolved")
        return self.internal_token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache process settings without reading a repository env file."""

    return Settings()  # type: ignore[call-arg]
