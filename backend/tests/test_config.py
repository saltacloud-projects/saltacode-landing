import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_rejects_process_local_rate_limiter() -> None:
    with pytest.raises(ValidationError, match="shared rate-limit backend"):
        Settings(app_env="production", rate_limit_backend="memory")


def test_redis_backend_requires_url() -> None:
    with pytest.raises(ValidationError, match="requires a Redis URL"):
        Settings(app_env="test", rate_limit_backend="redis")


def test_redis_url_rejects_non_redis_scheme() -> None:
    with pytest.raises(ValidationError, match="must use redis or rediss"):
        Settings(app_env="test", rate_limit_backend="redis", redis_url="http://redis:6379")


def test_production_accepts_redis_and_secret_file(tmp_path) -> None:
    token_file = tmp_path / "agent-token"
    token_file.write_text(f"{'x' * 32}\n", encoding="utf-8")

    settings = Settings(
        app_env="production",
        agent_ai_base_url="http://agent-ai:8001",
        agent_internal_token_file=token_file,
        rate_limit_backend="redis",
        redis_url="redis://redis:6379/0",
    )

    assert settings.rate_limit_backend == "redis"
    assert settings.resolve_redis_url() == "redis://redis:6379/0"


def test_allowed_origin_rejects_paths() -> None:
    with pytest.raises(ValidationError, match="must not contain a path"):
        Settings(allowed_origins="https://saltacode.com.ar/api")


def test_agent_ai_base_url_rejects_paths() -> None:
    with pytest.raises(ValidationError, match="must not contain a path"):
        Settings(agent_ai_base_url="http://agent-ai:8001/internal")


def test_agent_ai_base_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="must not contain credentials"):
        Settings(agent_ai_base_url="http://user:password@agent-ai:8001")


def test_agent_ai_base_url_requires_token_outside_tests() -> None:
    with pytest.raises(ValidationError, match="requires an internal token"):
        Settings(agent_ai_base_url="http://agent-ai:8001")


def test_agent_internal_token_file_fails_closed_when_missing(tmp_path) -> None:
    with pytest.raises(ValidationError, match="file is unreadable"):
        Settings(
            agent_ai_base_url="http://agent-ai:8001",
            agent_internal_token_file=tmp_path / "missing",
        )


def test_agent_internal_token_file_fails_closed_when_short(tmp_path) -> None:
    token_file = tmp_path / "agent-token"
    token_file.write_text("too-short\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(
            agent_ai_base_url="http://agent-ai:8001",
            agent_internal_token_file=token_file,
        )


def test_agent_internal_token_file_is_resolved_without_newline(tmp_path) -> None:
    token_file = tmp_path / "agent-token"
    token_file.write_text(f"{'x' * 32}\n", encoding="utf-8")

    settings = Settings(
        agent_ai_base_url="http://agent-ai:8001",
        agent_internal_token_file=token_file,
    )

    assert settings.resolve_agent_internal_token() == "x" * 32
