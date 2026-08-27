#!/usr/bin/env python3
"""Copy a Compose-mounted root secret, drop privileges, then exec the service."""

from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path

_SECRET_SOURCE_DEFAULT = "/run/secrets/source_master_key"
_SECRET_TARGET_DEFAULT = "/run/agent-secrets/source_master.key"
_SECRET_TARGET_ROOT = Path("/run/agent-secrets")
_MAX_SECRET_BYTES = 4096


def _copy_secret(source: Path, target: Path, *, uid: int, gid: int) -> None:
    payload = bytearray()
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with source.open("rb") as handle:
            payload.extend(handle.read(_MAX_SECRET_BYTES + 1))
        if not payload or len(payload) > _MAX_SECRET_BYTES:
            raise RuntimeError("credential encryption key has an invalid size")
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
        raise RuntimeError("credential encryption key could not be prepared") from exc
    finally:
        for index in range(len(payload)):
            payload[index] = 0
        temporary.unlink(missing_ok=True)


def _set_unprivileged_environment(*, username: str, home: str) -> None:
    os.environ["HOME"] = home
    os.environ["USER"] = username
    os.environ["LOGNAME"] = username


def main() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("container entrypoint must start as root")
    if len(sys.argv) < 2:
        raise RuntimeError("container command is required")

    account = pwd.getpwnam("appuser")
    source = Path(
        os.environ.get("CREDENTIAL_ENCRYPTION_KEY_SOURCE_FILE", _SECRET_SOURCE_DEFAULT)
    )
    target = Path(
        os.environ.get("CREDENTIAL_ENCRYPTION_KEY_FILE", _SECRET_TARGET_DEFAULT)
    )
    try:
        target.relative_to(_SECRET_TARGET_ROOT)
    except ValueError as exc:
        raise RuntimeError(
            "credential encryption key target is outside the secure runtime directory"
        ) from exc

    _copy_secret(source, target, uid=account.pw_uid, gid=account.pw_gid)
    _set_unprivileged_environment(username=account.pw_name, home=account.pw_dir)
    os.umask(0o077)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    if not os.access(target, os.R_OK):
        raise RuntimeError(
            "credential encryption key is not readable after privilege drop"
        )
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
