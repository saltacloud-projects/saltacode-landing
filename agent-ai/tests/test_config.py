from pathlib import Path

import pytest
from pydantic import ValidationError

from saltacode_agent.config import Settings

TOKEN = "file-token-that-is-longer-than-thirty-two-characters"


def write_secret(tmp_path: Path, value: str = TOKEN) -> Path:
    secret_file = tmp_path / "internal_token"
    secret_file.write_text(value, encoding="utf-8")
    return secret_file


def test_production_reads_redacted_token_from_secret_file(tmp_path: Path) -> None:
    secret_file = write_secret(tmp_path, f"{TOKEN}\n")

    settings = Settings(environment="production", internal_token_file=secret_file)

    assert settings.resolved_internal_token.get_secret_value() == TOKEN
    assert str(settings.resolved_internal_token) == "**********"


@pytest.mark.parametrize("value", ["short\n", " " * 32])
def test_secret_file_rejects_invalid_values(tmp_path: Path, value: str) -> None:
    secret_file = write_secret(tmp_path, value)

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(environment="production", internal_token_file=secret_file)


def test_secret_file_fails_closed_when_missing(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="not readable"):
        Settings(environment="production", internal_token_file=tmp_path / "missing")


def test_secret_file_fails_closed_when_path_is_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="not readable"):
        Settings(environment="production", internal_token_file=tmp_path)


def test_token_sources_are_mutually_exclusive(tmp_path: Path) -> None:
    secret_file = write_secret(tmp_path)

    with pytest.raises(ValidationError, match="exactly one"):
        Settings(
            environment="testing",
            internal_token=TOKEN,
            internal_token_file=secret_file,
        )


def test_production_rejects_direct_environment_token() -> None:
    with pytest.raises(ValidationError, match="production requires"):
        Settings(environment="production", internal_token=TOKEN)


def test_development_accepts_direct_environment_token() -> None:
    settings = Settings(environment="development", internal_token=TOKEN)

    assert settings.resolved_internal_token.get_secret_value() == TOKEN
