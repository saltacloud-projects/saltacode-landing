#!/usr/bin/env python3
"""Read-only, secret-free diagnostics for the local agentic toolchain."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLASSIFICATIONS = {"required", "recommended", "external"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class Requirement:
    key: str
    classification: str
    command: str
    minimum_version: tuple[int, int, int]
    minimum_display: str
    version_args: tuple[str, ...]
    version_pattern: re.Pattern[str]


class Doctor:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.required_failures = 0
        self.available: dict[str, bool] = {}
        self.safe_environment = os.environ.copy()
        self.safe_environment["ENGRAM_CLOUD_AUTOSYNC"] = "0"

    def emit(self, status: str, classification: str, label: str, message: str) -> None:
        print(f"[{status}][{classification}] {label}: {message}")

    def problem(self, requirement: Requirement, message: str) -> None:
        if requirement.classification == "required":
            self.required_failures += 1
            self.emit("FAIL", requirement.classification, requirement.key, message)
        elif requirement.classification == "recommended":
            self.emit("WARN", requirement.classification, requirement.key, message)
        else:
            self.emit("INFO", requirement.classification, requirement.key, message)

    def run(self, command: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=self.root,
                env=self.safe_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(
                command,
                124,
                stdout="",
                stderr=type(exc).__name__,
            )

    def check_tool(self, requirement: Requirement) -> None:
        executable = shutil.which(requirement.command)
        if executable is None:
            self.available[requirement.key] = False
            self.problem(requirement, f"{requirement.command} is not installed")
            return
        completed = self.run([executable, *requirement.version_args])
        output = f"{completed.stdout}\n{completed.stderr}"
        match = requirement.version_pattern.search(output)
        if completed.returncode != 0 or match is None:
            self.available[requirement.key] = False
            self.problem(requirement, "version output did not match the declared contract")
            return
        version = tuple(int(part) for part in match.group("version").split("."))
        self.available[requirement.key] = True
        if version < requirement.minimum_version:
            self.problem(
                requirement,
                f"version {match.group('version')} is below {requirement.minimum_display}",
            )
            return
        self.emit(
            "PASS",
            requirement.classification,
            requirement.key,
            f"version {match.group('version')}",
        )

    def check_repository(self) -> None:
        if not self.available.get("git"):
            return
        completed = self.run(["git", "rev-parse", "--show-toplevel"])
        if completed.returncode != 0:
            self.required_failures += 1
            self.emit("FAIL", "required", "git_repository", "not inside a Git worktree")
            return
        detected = Path(completed.stdout.strip()).resolve()
        if detected != self.root:
            self.required_failures += 1
            self.emit(
                "FAIL",
                "required",
                "git_repository",
                "detected root does not match the script root",
            )
            return
        status = self.run(["git", "status", "--porcelain=v1", "--untracked-files=normal"])
        if status.returncode != 0:
            self.required_failures += 1
            self.emit("FAIL", "required", "git_repository", "could not read worktree status")
            return
        changes = sum(1 for line in status.stdout.splitlines() if line)
        detail = (
            "clean worktree" if changes == 0 else f"worktree readable ({changes} changed paths)"
        )
        self.emit("PASS", "required", "git_repository", detail)

    def check_docker_daemon(self) -> None:
        if not self.available.get("docker"):
            return
        completed = self.run(["docker", "info", "--format", "{{.ServerVersion}}"])
        if completed.returncode != 0 or not completed.stdout.strip():
            self.required_failures += 1
            self.emit("FAIL", "required", "docker_daemon", "local daemon is unavailable")
            return
        self.emit(
            "PASS",
            "required",
            "docker_daemon",
            f"local server {completed.stdout.strip()}",
        )

    def check_codegraph(self) -> None:
        if not self.available.get("codegraph"):
            return
        if not (self.root / ".codegraph").is_dir():
            self.emit("WARN", "recommended", "codegraph_index", "repository index is missing")
            return
        completed = self.run(["codegraph", "status"], timeout=20)
        if completed.returncode != 0:
            self.emit("WARN", "recommended", "codegraph_index", "status probe failed")
            return
        if "Index is up to date" not in completed.stdout:
            self.emit(
                "WARN",
                "recommended",
                "codegraph_index",
                "index is present but not current",
            )
            return
        self.emit("PASS", "recommended", "codegraph_index", "repository index is current")

    def check_codex_mcp(self) -> None:
        if not self.available.get("codex"):
            return
        completed = self.run(["codex", "mcp", "list", "--json"], timeout=20)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            self.emit("WARN", "recommended", "codex_mcp", "MCP list returned no safe JSON")
            return
        if completed.returncode != 0 or not isinstance(payload, list):
            self.emit("WARN", "recommended", "codex_mcp", "MCP list is unavailable")
            return
        names = sorted(
            item["name"]
            for item in payload
            if isinstance(item, dict)
            and item.get("enabled") is True
            and isinstance(item.get("name"), str)
            and "codegraph" in item["name"].casefold()
        )
        if len(names) > 1:
            self.emit(
                "WARN",
                "recommended",
                "codex_mcp",
                f"{len(names)} enabled CodeGraph MCPs ({', '.join(names)}); "
                "prefer the upstream repository index; global configuration unchanged",
            )
            return
        if names:
            self.emit(
                "PASS",
                "recommended",
                "codex_mcp",
                f"one enabled CodeGraph MCP ({names[0]})",
            )
            return
        self.emit("WARN", "recommended", "codex_mcp", "no enabled CodeGraph MCP")

    def check_engram(self) -> None:
        if not self.available.get("engram"):
            return
        completed = self.run(
            ["engram", "doctor", "--json", "--project", self.root.name], timeout=20
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            self.emit(
                "INFO",
                "external",
                "engram_health",
                "doctor returned no safe JSON summary",
            )
            return
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        status = payload.get("status", "unknown") if isinstance(payload, dict) else "unknown"
        safe_counts = {
            key: value
            for key in ("ok", "warnings", "blocked", "errors")
            if isinstance((value := summary.get(key)), int)
        }
        counts = ", ".join(f"{key}={value}" for key, value in safe_counts.items())
        label = "PASS" if completed.returncode == 0 and status == "ok" else "INFO"
        detail = f"local doctor status={status}"
        if counts:
            detail = f"{detail} ({counts})"
        self.emit(label, "external", "engram_health", detail)


def parse_version(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or SEMVER.fullmatch(value) is None:
        raise ValueError(f"{label} must use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def load_requirements(path: Path) -> list[Requirement]:
    try:
        with path.open("rb") as handle:
            manifest = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot load {path}: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise ValueError("tool requirements schema_version must be 1")
    tools = manifest.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise ValueError("tool requirements must define at least one [tools.*] table")

    requirements: list[Requirement] = []
    for key, raw in tools.items():
        if not isinstance(raw, dict):
            raise TypeError(f"tools.{key} must be a TOML table")
        classification = raw.get("classification")
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"tools.{key}.classification is invalid")
        command = raw.get("command")
        args = raw.get("version_args")
        pattern = raw.get("version_pattern")
        minimum = raw.get("minimum_version")
        if not isinstance(command, str) or not command:
            raise ValueError(f"tools.{key}.command must be non-empty")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError(f"tools.{key}.version_args must be a string array")
        if not isinstance(pattern, str) or "?P<version>" not in pattern:
            raise ValueError(f"tools.{key}.version_pattern needs a named version group")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"tools.{key}.version_pattern is invalid: {exc}") from exc
        requirements.append(
            Requirement(
                key=key,
                classification=classification,
                command=command,
                minimum_version=parse_version(minimum, f"tools.{key}.minimum_version"),
                minimum_display=minimum,
                version_args=tuple(args),
                version_pattern=compiled,
            )
        )
    return requirements


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path.cwd()).resolve()
    manifest_path = root / "scripts/agentic/tool-requirements.toml"
    try:
        requirements = load_requirements(manifest_path)
    except (TypeError, ValueError) as exc:
        print(f"[FAIL][required] tool_manifest: {exc}", file=sys.stderr)
        return 1

    doctor = Doctor(root)
    for requirement in requirements:
        doctor.check_tool(requirement)
    doctor.check_repository()
    doctor.check_docker_daemon()
    doctor.check_codegraph()
    doctor.check_codex_mcp()
    doctor.check_engram()

    if doctor.required_failures:
        print(
            f"Agentic doctor failed: {doctor.required_failures} required check(s) failed.",
            file=sys.stderr,
        )
        return 1
    print("Agentic doctor passed: all required checks are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
