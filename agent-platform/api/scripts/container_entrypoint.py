#!/usr/bin/env python3
"""Prepare file-mounted secrets, drop privileges, then exec the service."""

from __future__ import annotations

import os
import pwd
import sys
from collections.abc import MutableMapping
from pathlib import Path

_SECRET_TARGET_ROOT = Path("/run/agent-secrets")
_INTERNAL_API_KEY_SOURCE_DEFAULT = "/run/secrets/internal_api_token"
_MAX_SECRET_BYTES = 4096
_LOCAL_ENVIRONMENTS = frozenset({"development", "testing"})
_JWT_PLACEHOLDER = "CHANGE-ME-IN-PRODUCTION"


_RUNTIME_SECRETS = (
    (
        "source master key",
        "CREDENTIAL_ENCRYPTION_KEY_SOURCE_FILE",
        "/run/secrets/source_master_key",
        "CREDENTIAL_ENCRYPTION_KEY_FILE",
        "/run/agent-secrets/source_master.key",
    ),
    (
        "contact data key",
        "CONTACT_ENCRYPTION_KEY_SOURCE_FILE",
        "/run/secrets/contact_data_key",
        "CONTACT_ENCRYPTION_KEY_FILE",
        "/run/agent-secrets/contact_data.key",
    ),
    (
        "contact lookup HMAC key",
        "CONTACT_LOOKUP_HMAC_KEY_SOURCE_FILE",
        "/run/secrets/contact_lookup_hmac_key",
        "CONTACT_LOOKUP_HMAC_KEY_FILE",
        "/run/agent-secrets/contact_lookup_hmac.key",
    ),
)


def _copy_secret(
    source: Path,
    target: Path,
    *,
    uid: int,
    gid: int,
    label: str = "runtime secret",
) -> None:
    payload = bytearray()
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with source.open("rb") as handle:
            payload.extend(handle.read(_MAX_SECRET_BYTES + 1))
        if not payload or len(payload) > _MAX_SECRET_BYTES:
            raise RuntimeError(f"{label} has an invalid size")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
        )
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("short write while preparing credential key")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o400)
            os.fchown(descriptor, uid, gid)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
    except OSError as exc:
        raise RuntimeError(f"{label} could not be prepared") from exc
    finally:
        for index in range(len(payload)):
            payload[index] = 0
        temporary.unlink(missing_ok=True)


def _set_unprivileged_environment(*, username: str, home: str) -> None:
    os.environ["HOME"] = home
    os.environ["USER"] = username
    os.environ["LOGNAME"] = username


def _read_secret(source: Path, *, label: str) -> str:
    payload = bytearray()
    try:
        with source.open("rb") as handle:
            payload.extend(handle.read(_MAX_SECRET_BYTES + 1))
        if not payload or len(payload) > _MAX_SECRET_BYTES:
            raise RuntimeError(f"{label} has an invalid size")
        value = bytes(payload).strip().decode("utf-8")
        if not value:
            raise RuntimeError(f"{label} is empty")
        return value
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"{label} could not be loaded") from exc
    finally:
        for index in range(len(payload)):
            payload[index] = 0


def _configure_security_environment(
    environment: MutableMapping[str, str],
) -> None:
    runtime_environment = environment.get("FASTAPI_ENV", "production").lower()
    api_key_source = Path(
        environment.get("FASTAPI_API_KEY_FILE", _INTERNAL_API_KEY_SOURCE_DEFAULT)
    )

    if api_key_source.is_file():
        environment["FASTAPI_API_KEY"] = _read_secret(
            api_key_source,
            label="internal API token",
        )
    elif not (
        runtime_environment in _LOCAL_ENVIRONMENTS
        and environment.get("FASTAPI_API_KEY")
    ):
        raise RuntimeError("internal API token file is required")

    jwt_secret = environment.get("JWT_SECRET_KEY", "")
    if runtime_environment not in _LOCAL_ENVIRONMENTS and (
        jwt_secret == _JWT_PLACEHOLDER or len(jwt_secret) < 32
    ):
        raise RuntimeError("a strong JWT secret is required outside local environments")


def _resolved_runtime_secrets(
    environment: MutableMapping[str, str],
) -> tuple[tuple[str, Path, Path], ...]:
    resolved = []
    targets = set()
    for (
        label,
        source_env,
        source_default,
        target_env,
        target_default,
    ) in _RUNTIME_SECRETS:
        source = Path(environment.get(source_env, source_default))
        target = Path(environment.get(target_env, target_default))
        try:
            target.relative_to(_SECRET_TARGET_ROOT)
        except ValueError as exc:
            raise RuntimeError(
                f"{label} target is outside the secure runtime directory"
            ) from exc
        if target in targets:
            raise RuntimeError("runtime secret targets must be unique")
        targets.add(target)
        resolved.append((label, source, target))
    return tuple(resolved)


def _read_secret_bytes(source: Path, *, label: str) -> bytearray:
    payload = bytearray()
    try:
        with source.open("rb") as handle:
            payload.extend(handle.read(_MAX_SECRET_BYTES + 1))
        if not payload or len(payload) > _MAX_SECRET_BYTES:
            raise RuntimeError(f"{label} has an invalid size")
        return payload
    except OSError as exc:
        raise RuntimeError(f"{label} could not be loaded") from exc


def _assert_distinct_contact_keys(
    resolved: tuple[tuple[str, Path, Path], ...],
) -> None:
    sources = {label: source for label, source, _target in resolved}
    encryption_payload = bytearray()
    lookup_payload = bytearray()
    try:
        encryption_payload = _read_secret_bytes(
            sources["contact data key"],
            label="contact data key",
        )
        lookup_payload = _read_secret_bytes(
            sources["contact lookup HMAC key"],
            label="contact lookup HMAC key",
        )
        if encryption_payload == lookup_payload:
            raise RuntimeError("contact encryption and lookup keys must be distinct")
    finally:
        for payload in (encryption_payload, lookup_payload):
            for index in range(len(payload)):
                payload[index] = 0


def _prepare_runtime_secrets(
    environment: MutableMapping[str, str],
    *,
    uid: int,
    gid: int,
) -> tuple[Path, ...]:
    resolved = _resolved_runtime_secrets(environment)
    _assert_distinct_contact_keys(resolved)
    for label, source, target in resolved:
        _copy_secret(
            source,
            target,
            uid=uid,
            gid=gid,
            label=label,
        )
    return tuple(target for _label, _source, target in resolved)


def main() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("container entrypoint must start as root")
    if len(sys.argv) < 2:
        raise RuntimeError("container command is required")

    account = pwd.getpwnam("appuser")
    _configure_security_environment(os.environ)
    targets = _prepare_runtime_secrets(
        os.environ,
        uid=account.pw_uid,
        gid=account.pw_gid,
    )
    _set_unprivileged_environment(username=account.pw_name, home=account.pw_dir)
    os.umask(0o077)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    for target in targets:
        if not os.access(target, os.R_OK):
            raise RuntimeError("runtime secret is not readable after privilege drop")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
