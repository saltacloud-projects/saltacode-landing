"""Security regression tests for the container secret handoff."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path


def _load_entrypoint():
    path = Path(__file__).parents[1] / "scripts" / "container_entrypoint.py"
    spec = importlib.util.spec_from_file_location("container_entrypoint", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_copy_is_private_and_does_not_modify_source(tmp_path):
    entrypoint = _load_entrypoint()
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
    entrypoint = _load_entrypoint()
    source = tmp_path / "empty-secret"
    target = tmp_path / "master.key"
    source.write_bytes(b"")

    try:
        entrypoint._copy_secret(source, target, uid=os.getuid(), gid=os.getgid())
    except RuntimeError as exc:
        assert "secret-value" not in str(exc)
        assert not target.exists()
    else:
        raise AssertionError("empty secrets must fail closed")


def test_privilege_drop_environment_does_not_retain_root_home(monkeypatch):
    entrypoint = _load_entrypoint()
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("LOGNAME", "root")

    entrypoint._set_unprivileged_environment(username="appuser", home="/app")

    assert os.environ["HOME"] == "/app"
    assert os.environ["USER"] == "appuser"
    assert os.environ["LOGNAME"] == "appuser"
