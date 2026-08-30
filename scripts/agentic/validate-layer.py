#!/usr/bin/env python3
"""Validate the repository-local Codex contract from its declared sources."""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ContractError(RuntimeError):
    """An actionable agentic contract violation."""


@dataclass(frozen=True)
class HumanAgent:
    name: str
    access: str


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
SKILL_SECTIONS = (
    "Activation Contract",
    "Hard Rules",
    "Decision Gates",
    "Execution Steps",
    "Output Contract",
    "References",
)
SANDBOX_ACCESS = {
    "Read-only": "read-only",
    "Workspace write": "workspace-write",
}
FORBIDDEN_CONFIG_KEYS = {
    "model",
    "model_reasoning_effort",
    "approval_policy",
}


def fail(message: str) -> None:
    raise ContractError(message)


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        fail(f"missing required TOML artifact: {path}")
    except tomllib.TOMLDecodeError as exc:
        fail(f"invalid TOML in {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"TOML root must be a table: {path}")
    return data


def load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"missing required artifact: {path}")
    except UnicodeDecodeError as exc:
        fail(f"artifact is not valid UTF-8: {path}: {exc}")


def markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    marker = f"## {heading}"
    try:
        start = lines.index(marker) + 1
    except ValueError:
        fail(f"Markdown contract is missing section: {heading}")
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def markdown_table(section: str, label: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        fail(f"{label} must contain a Markdown table with at least one entry")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        fail(f"{label} contains an inconsistent Markdown table")
    return rows[1:]


def inline_code(value: str, label: str) -> str:
    match = re.fullmatch(r"`([^`]+)`", value.strip())
    if match is None:
        fail(f"{label} must use one inline-code value")
    return match.group(1)


def resolve_repo_reference(root: Path, source: Path, reference: str) -> Path:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", reference):
        fail(f"{source} contains a non-local reference: {reference}")
    candidate = (source.parent / reference).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        fail(f"{source} reference escapes the repository: {reference}")
    if not candidate.exists():
        fail(f"{source} references a missing local artifact: {reference}")
    return candidate


def parse_scalar(raw_value: str, path: Path, number: int) -> str:
    value = raw_value.strip()
    if value.startswith(('"', "'")):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            fail(f"{path}:{number} has an invalid quoted frontmatter value: {exc}")
        if not isinstance(parsed, str):
            fail(f"{path}:{number} frontmatter values must be strings")
        return parsed
    if any(token in value for token in ("[", "]", "{", "}", "&", "*")):
        fail(f"{path}:{number} uses unsupported complex frontmatter syntax")
    return value


def parse_frontmatter(path: Path, text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        fail(f"{path} has no opening frontmatter delimiter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        fail(f"{path} has no closing frontmatter delimiter")

    result: dict[str, Any] = {}
    current_table: dict[str, Any] | None = None
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  "):
            if current_table is None:
                fail(f"{path}:{number} has an orphan nested frontmatter key")
            match = re.fullmatch(r"  ([A-Za-z_][A-Za-z0-9_-]*):\s*(.+)", line)
            if match is None:
                fail(f"{path}:{number} has unsupported frontmatter syntax")
            key, raw_value = match.groups()
            if key in current_table:
                fail(f"{path}:{number} duplicates frontmatter key: {key}")
            current_table[key] = parse_scalar(raw_value, path, number)
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?", line)
        if match is None:
            fail(f"{path}:{number} has unsupported frontmatter syntax")
        key, raw_value = match.groups()
        if key in result:
            fail(f"{path}:{number} duplicates frontmatter key: {key}")
        if not raw_value:
            current_table = {}
            result[key] = current_table
        else:
            result[key] = parse_scalar(raw_value, path, number)
            current_table = None
    return result


def validate_skill(root: Path, path: Path) -> str:
    text = load_text(path)
    metadata = parse_frontmatter(path, text)
    expected_name = path.parent.name
    if metadata.get("name") != expected_name:
        fail(f"{path} frontmatter name must be {expected_name!r}")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.startswith("Trigger: "):
        fail(f"{path} description must be a non-empty Trigger contract")
    if len(description) > 250:
        fail(f"{path} description exceeds 250 characters")
    if metadata.get("license") != "Apache-2.0":
        fail(f"{path} license must be Apache-2.0")
    nested = metadata.get("metadata")
    if not isinstance(nested, dict):
        fail(f"{path} frontmatter must define metadata")
    if nested.get("author") != "Oscar Vargas":
        fail(f"{path} metadata.author must be Oscar Vargas")
    version = nested.get("version")
    if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
        fail(f"{path} metadata.version must be valid SemVer 2 (MAJOR.MINOR.PATCH)")

    positions: list[int] = []
    lines = text.splitlines()
    frontmatter_end = lines.index("---", 1)
    body_words = len(re.findall(r"\S+", "\n".join(lines[frontmatter_end + 1 :])))
    if body_words > 1000:
        fail(f"{path} body exceeds the 1000-word runtime contract limit")
    for section in SKILL_SECTIONS:
        marker = f"## {section}"
        matches = [index for index, line in enumerate(lines) if line == marker]
        if len(matches) != 1:
            fail(f"{path} must contain exactly one section: {section}")
        positions.append(matches[0])
    if positions != sorted(positions):
        fail(f"{path} has required sections out of order")

    references_start = positions[-1] + 1
    references_end = next(
        (index for index in range(references_start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    references: list[str] = []
    for number, line in enumerate(lines[references_start:references_end], references_start + 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"-\s+`([^`]+)`", line.strip())
        if match is None:
            fail(f"{path}:{number} references must be local inline-code paths")
        references.append(match.group(1))
    if not references:
        fail(f"{path} must declare at least one local reference")
    for reference in references:
        resolve_repo_reference(root, path, reference)
    if re.search(r"https?://", text, flags=re.IGNORECASE):
        fail(f"{path} contains a non-local URL")
    return expected_name


def validate_human_references(root: Path, agents_path: Path, text: str) -> None:
    for reference in sorted(set(re.findall(r"`([^`]+)`", text))):
        if any(character.isspace() for character in reference):
            continue
        looks_like_path = "/" in reference or reference.endswith(
            (".md", ".toml", ".yml", ".yaml", ".json")
        )
        if not looks_like_path:
            continue
        resolve_repo_reference(root, agents_path, reference)


def validate_agents(root: Path, agents_text: str) -> set[str]:
    config_path = root / ".codex/config.toml"
    config = load_toml(config_path)
    forbidden = FORBIDDEN_CONFIG_KEYS | {"sandbox_mode"}
    present_forbidden = sorted(forbidden.intersection(config))
    if present_forbidden:
        fail(f"{config_path} pins forbidden root settings: {', '.join(present_forbidden)}")
    agent_config = config.get("agents")
    if not isinstance(agent_config, dict):
        fail(f"{config_path} must define an [agents] table")
    if agent_config.get("enabled") is not True:
        fail(f"{config_path} agents.enabled must be true")
    concurrency = agent_config.get("max_concurrent_threads_per_session")
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency < 1:
        fail(f"{config_path} agent concurrency must be a positive integer")

    declared = {key: value for key, value in agent_config.items() if isinstance(value, dict)}
    if not declared:
        fail(f"{config_path} declares no project agents")
    unexpected_scalars = sorted(
        key
        for key, value in agent_config.items()
        if key not in {"enabled", "max_concurrent_threads_per_session"}
        and not isinstance(value, dict)
    )
    if unexpected_scalars:
        fail(f"{config_path} has invalid agent entries: {', '.join(unexpected_scalars)}")

    discovered_files = sorted((root / ".codex/agents").glob("*.toml"))
    discovered = {path.stem: path for path in discovered_files}
    if set(declared) != set(discovered):
        fail(
            "agent config/files drift: "
            f"config-only={sorted(set(declared) - set(discovered))}, "
            f"files-only={sorted(set(discovered) - set(declared))}"
        )

    human_rows = markdown_table(markdown_section(agents_text, "Project agents"), "Project agents")
    human_agents: dict[str, HumanAgent] = {}
    for row in human_rows:
        if len(row) < 3:
            fail("Project agents rows must provide Agent, Access, and Use")
        name = inline_code(row[0], "Project agents Agent")
        if name in human_agents:
            fail(f"Project agents duplicates agent: {name}")
        if not row[2].strip():
            fail(f"Project agents entry {name} needs a non-empty purpose")
        human_agents[name] = HumanAgent(name=name, access=row[1].strip())
    if set(human_agents) != set(discovered):
        fail(
            "AGENTS.md/config agent drift: "
            f"human-only={sorted(set(human_agents) - set(discovered))}, "
            f"config-only={sorted(set(discovered) - set(human_agents))}"
        )

    referenced_paths: set[Path] = set()
    for name, entry in declared.items():
        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(f"{config_path} agent {name} needs a description")
        config_file = entry.get("config_file")
        if not isinstance(config_file, str) or not config_file.strip():
            fail(f"{config_path} agent {name} needs config_file")
        resolved = (config_path.parent / config_file).resolve()
        try:
            resolved.relative_to((root / ".codex/agents").resolve())
        except ValueError:
            fail(f"{config_path} agent {name} config_file escapes .codex/agents")
        if resolved != discovered[name].resolve():
            fail(f"{config_path} agent {name} config_file does not match its discovered TOML")
        if resolved in referenced_paths:
            fail(f"{config_path} reuses one config_file for multiple agents: {config_file}")
        referenced_paths.add(resolved)

        definition = load_toml(resolved)
        if definition.get("name") != name:
            fail(f"{resolved} name must match its config key: {name}")
        if definition.get("description") != description:
            fail(f"{resolved} description differs from {config_path}")
        instructions = definition.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            fail(f"{resolved} needs non-empty developer_instructions")
        forbidden_agent_keys = sorted(FORBIDDEN_CONFIG_KEYS.intersection(definition))
        if forbidden_agent_keys:
            fail(f"{resolved} pins forbidden settings: {', '.join(forbidden_agent_keys)}")
        sandbox_mode = definition.get("sandbox_mode")
        expected_sandbox = SANDBOX_ACCESS.get(human_agents[name].access)
        if expected_sandbox is None:
            fail(f"AGENTS.md agent {name} uses unsupported access: {human_agents[name].access}")
        if sandbox_mode != expected_sandbox:
            fail(
                f"{resolved} sandbox_mode {sandbox_mode!r} does not match "
                f"AGENTS.md access {human_agents[name].access!r}"
            )
    return set(discovered)


def validate_skills(root: Path, agents_text: str) -> set[str]:
    skills_root = root / ".agents/skills"
    if not skills_root.is_dir():
        fail(f"missing project skills directory: {skills_root}")
    skill_directories = sorted(path for path in skills_root.iterdir() if path.is_dir())
    missing_entrypoints = [
        str(path) for path in skill_directories if not (path / "SKILL.md").is_file()
    ]
    if missing_entrypoints:
        fail(f"skill directories without SKILL.md: {', '.join(missing_entrypoints)}")
    skill_paths = [path / "SKILL.md" for path in skill_directories]
    if not skill_paths:
        fail("no project skills were discovered")
    discovered: dict[str, Path] = {}
    for path in skill_paths:
        name = validate_skill(root, path)
        if name in discovered:
            fail(f"duplicate discovered skill name: {name}")
        discovered[name] = path

    human_rows = markdown_table(markdown_section(agents_text, "Project skills"), "Project skills")
    human: dict[str, Path] = {}
    for row in human_rows:
        if len(row) < 2:
            fail("Project skills rows must provide Skill and Trigger")
        reference = inline_code(row[0], "Project skills Skill")
        path = resolve_repo_reference(root, root / "AGENTS.md", reference)
        if path.name != "SKILL.md" or path.parent.parent != skills_root:
            fail(f"AGENTS.md project skill is outside .agents/skills: {reference}")
        name = path.parent.name
        if name in human:
            fail(f"Project skills duplicates skill: {name}")
        if not row[1].strip():
            fail(f"Project skills entry {name} needs a non-empty trigger")
        human[name] = path
    if set(human) != set(discovered):
        fail(
            "AGENTS.md/skill directory drift: "
            f"human-only={sorted(set(human) - set(discovered))}, "
            f"files-only={sorted(set(discovered) - set(human))}"
        )

    registry_path = root / ".atl/skill-registry.md"
    if registry_path.exists():
        registry_text = load_text(registry_path)
        registry_rows = markdown_table(markdown_section(registry_text, "Skills"), "skill registry")
        registered: dict[str, Path] = {}
        for row in registry_rows:
            if len(row) < 4 or row[2].strip() != "project":
                continue
            name = inline_code(row[0], "skill registry Skill")
            raw_path = inline_code(row[3], f"skill registry path for {name}")
            path = Path(raw_path)
            resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
            if name in registered:
                fail(f"skill registry duplicates project skill: {name}")
            registered[name] = resolved
        if set(registered) != set(discovered):
            fail(
                "skill registry/project skill drift: "
                f"registry-only={sorted(set(registered) - set(discovered))}, "
                f"files-only={sorted(set(discovered) - set(registered))}"
            )
        for name, path in discovered.items():
            if registered[name] != path.resolve():
                fail(f"skill registry path for {name} does not resolve to {path}")

    cache_path = root / ".atl/.skill-registry.cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(load_text(cache_path))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON in {cache_path}: {exc}")
        fingerprint = str(cache.get("fingerprint", "")) if isinstance(cache, dict) else ""
        if re.fullmatch(r"[0-9a-f]{40}", fingerprint) is None:
            fail(f"{cache_path} must contain a SHA-1 fingerprint")
    return set(discovered)


def validate_manifest_artifacts(root: Path) -> None:
    manifest_path = root / "scripts/agentic/tool-requirements.toml"
    manifest = load_toml(manifest_path)
    if manifest.get("schema_version") != 1:
        fail(f"{manifest_path} schema_version must be 1")
    contract = manifest.get("agentic")
    if not isinstance(contract, dict):
        fail(f"{manifest_path} must define [agentic]")
    for key, executable in (
        ("required_artifacts", False),
        ("required_entrypoints", True),
    ):
        references = contract.get(key)
        if (
            not isinstance(references, list)
            or not references
            or not all(isinstance(reference, str) and reference for reference in references)
        ):
            fail(f"{manifest_path} agentic.{key} must be a non-empty string array")
        if len(references) != len(set(references)):
            fail(f"{manifest_path} agentic.{key} contains duplicate paths")
        for reference in references:
            path = resolve_repo_reference(root, root / "agentic-manifest.toml", reference)
            if not path.is_file():
                fail(f"required agentic artifact is not a regular file: {reference}")
            if executable and not os.access(path, os.X_OK):
                fail(f"required agentic entrypoint is not executable: {reference}")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path.cwd()).resolve()
    validate_manifest_artifacts(root)
    agents_path = root / "AGENTS.md"
    agents_text = load_text(agents_path)
    validate_human_references(root, agents_path, agents_text)
    agents = validate_agents(root, agents_text)
    skills = validate_skills(root, agents_text)
    print(f"Agentic layer validation passed: {len(agents)} agents, {len(skills)} skills.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
