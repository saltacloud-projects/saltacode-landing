"""Security contract tests for the privileged container entrypoint."""

import importlib.util
import os
import stat
from pathlib import Path

import pytest


def _load_entrypoint_module():
    path = Path(__file__).parents[1] / "scripts" / "container_entrypoint.py"
    spec = importlib.util.spec_from_file_location("agent_container_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entrypoint = _load_entrypoint_module()


def test_secret_copy_is_private_and_does_not_modify_source(tmp_path):
    source = tmp_path / "compose-secret"
    target = tmp_path / "runtime" / "master.key"
    target.parent.mkdir()
    source.write_bytes(b"test-master-key")
    source.chmod(0o600)

    entrypoint._copy_secret(
        source,
        target,
        uid=os.getuid(),
        gid=os.getgid(),
    )

    assert target.read_bytes() == b"test-master-key"
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    assert stat.S_IMODE(source.stat().st_mode) == 0o600


def test_secret_copy_error_never_contains_secret_value(tmp_path):
    source = tmp_path / "empty-secret"
    target = tmp_path / "master.key"
    source.write_bytes(b"")

    with pytest.raises(RuntimeError) as error:
        entrypoint._copy_secret(source, target, uid=os.getuid(), gid=os.getgid())

    assert "secret-value" not in str(error.value)
    assert not target.exists()


def test_privilege_drop_environment_does_not_retain_root_home(monkeypatch):
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("LOGNAME", "root")

    entrypoint._set_unprivileged_environment(username="appuser", home="/app")

    assert os.environ["HOME"] == "/app"
    assert os.environ["USER"] == "appuser"
    assert os.environ["LOGNAME"] == "appuser"


def test_file_mounted_internal_token_wins_over_ambient_environment(tmp_path):
    token_file = tmp_path / "internal_api_token"
    token_file.write_text("mounted-secret\n", encoding="utf-8")
    environment = {
        "FASTAPI_ENV": "production",
        "FASTAPI_API_KEY": "stale-environment-value",
        "FASTAPI_API_KEY_FILE": str(token_file),
        "JWT_SECRET_KEY": "j" * 32,
    }

    entrypoint._configure_security_environment(environment)

    assert environment["FASTAPI_API_KEY"] == "mounted-secret"


@pytest.mark.parametrize("runtime_environment", ["development", "testing"])
def test_local_environments_allow_explicit_api_key_fallback(runtime_environment):
    environment = {
        "FASTAPI_ENV": runtime_environment,
        "FASTAPI_API_KEY": "local-only-key",
    }

    entrypoint._configure_security_environment(environment)

    assert environment["FASTAPI_API_KEY"] == "local-only-key"


def test_production_requires_file_mounted_internal_token():
    environment = {
        "FASTAPI_ENV": "production",
        "FASTAPI_API_KEY": "ambient-key-is-not-authoritative",
        "JWT_SECRET_KEY": "j" * 32,
    }

    with pytest.raises(RuntimeError, match="token file is required"):
        entrypoint._configure_security_environment(environment)


@pytest.mark.parametrize("jwt_secret", ["", "short", "CHANGE-ME-IN-PRODUCTION"])
def test_production_rejects_weak_or_placeholder_jwt_secret(tmp_path, jwt_secret):
    token_file = tmp_path / "internal_api_token"
    token_file.write_text("mounted-secret\n", encoding="utf-8")
    environment = {
        "FASTAPI_ENV": "production",
        "FASTAPI_API_KEY_FILE": str(token_file),
        "JWT_SECRET_KEY": jwt_secret,
    }

    with pytest.raises(RuntimeError, match="strong JWT secret"):
        entrypoint._configure_security_environment(environment)
