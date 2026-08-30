#!/usr/bin/env python3
"""Validate Conventional Commit messages without mutating repository state."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

CONVENTIONAL_SUBJECT = re.compile(r"^[a-z][a-z0-9-]*(?:\([A-Za-z0-9][A-Za-z0-9._/-]*\))?!?: \S.*$")
CO_AUTHOR_TRAILER = re.compile(r"(?im)^\s*co-authored-by\s*:")
AI_TRAILER = re.compile(
    r"(?im)^\s*(?:"
    r"ai[-_ ]?(?:authored|assisted|generated)(?:[-_ ]by)?\s*:"
    r"|(?:generated|created|written|assisted)[-_ ]by\s*:\s*"
    r"(?:ai|chatgpt|openai|codex|claude|gemini|copilot)\b"
    r")"
)
AI_SENTENCE = re.compile(
    r"(?im)^\s*(?:🤖\s*)?(?:generated|created|written|assisted)\s+"
    r"(?:with|by)\s+\[?(?:ai|chatgpt|openai|codex|claude|gemini|copilot)\b"
)
ZERO_OBJECT = re.compile(r"^0{40}(?:0{24})?$")


class ValidationError(RuntimeError):
    """Invalid input, unavailable history, or a rejected commit message."""


def git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def resolve_commit(repository: Path, revision: str) -> str:
    completed = git(
        repository,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
    )
    if completed.returncode != 0:
        raise ValidationError(
            f"commit {revision!r} is unavailable; fetch complete history before validation"
        )
    return completed.stdout.strip()


def commits_in_range(
    repository: Path,
    base: str,
    head: str,
    new_branch_base: str | None,
) -> list[str]:
    resolved_head = resolve_commit(repository, head)
    if ZERO_OBJECT.fullmatch(base):
        if new_branch_base is None:
            raise ValidationError(
                "an all-zero BASE has no implicit commit boundary; "
                "pass --new-branch-base with a fully fetched reference"
            )
        resolved_base = resolve_commit(repository, new_branch_base)
        revision = f"{resolved_base}..{resolved_head}"
    else:
        if new_branch_base is not None:
            raise ValidationError("--new-branch-base is valid only with an all-zero BASE")
        resolved_base = resolve_commit(repository, base)
        revision = f"{resolved_base}..{resolved_head}"
    completed = git(repository, "rev-list", "--reverse", revision)
    if completed.returncode != 0:
        raise ValidationError("Git could not enumerate the requested commit range")
    return [line for line in completed.stdout.splitlines() if line]


def exact_commits(repository: Path, revisions: list[str]) -> list[str]:
    commits: list[str] = []
    seen: set[str] = set()
    for revision in revisions:
        commit = resolve_commit(repository, revision)
        if commit not in seen:
            commits.append(commit)
            seen.add(commit)
    return commits


def commit_message(repository: Path, commit: str) -> str:
    completed = git(repository, "show", "-s", "--format=%B", commit)
    if completed.returncode != 0:
        raise ValidationError(f"could not read commit message for {commit[:12]}")
    return completed.stdout.rstrip("\n")


def message_errors(message: str) -> list[str]:
    errors: list[str] = []
    subject = message.splitlines()[0] if message.splitlines() else ""
    if CONVENTIONAL_SUBJECT.fullmatch(subject) is None:
        errors.append("subject is not a Conventional Commit")
    if CO_AUTHOR_TRAILER.search(message):
        errors.append("Co-Authored-By trailers are forbidden")
    if AI_TRAILER.search(message) or AI_SENTENCE.search(message):
        errors.append("AI attribution is forbidden")
    return errors


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Validate complete PR/push commit ranges or explicit commits without mutation."
        )
    )
    result.add_argument(
        "--repository",
        type=Path,
        default=Path.cwd(),
        help=argparse.SUPPRESS,
    )
    result.add_argument(
        "--new-branch-base",
        help=(
            "explicit fully fetched default-branch reference for a new-branch push "
            "whose BASE is all zeros"
        ),
    )
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--range",
        nargs=2,
        metavar=("BASE", "HEAD"),
        help=("validate BASE..HEAD; an all-zero BASE requires --new-branch-base"),
    )
    mode.add_argument(
        "--commits",
        nargs="+",
        metavar="COMMIT",
        help="validate one or more exact commits",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    repository = args.repository.resolve()
    inside = git(repository, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        print("ERROR: repository is not a Git worktree", file=sys.stderr)
        return 2

    try:
        commits = (
            commits_in_range(repository, *args.range, args.new_branch_base)
            if args.range is not None
            else exact_commits(repository, args.commits)
        )
        if args.range is None and args.new_branch_base is not None:
            raise ValidationError("--new-branch-base requires --range")
        failures: list[tuple[str, list[str]]] = []
        for commit in commits:
            errors = message_errors(commit_message(repository, commit))
            if errors:
                failures.append((commit, errors))
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for commit, errors in failures:
        for error in errors:
            print(f"ERROR: commit {commit[:12]}: {error}", file=sys.stderr)
    if failures:
        print(
            f"Commit validation failed: {len(failures)} of {len(commits)} commit(s) rejected.",
            file=sys.stderr,
        )
        return 1
    print(f"Commit validation passed: {len(commits)} commit(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
